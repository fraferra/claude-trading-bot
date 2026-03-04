"""Research Agent Monitor — runs the full Discovery→Research→Selector→Executor pipeline."""

from __future__ import annotations

import asyncio
import json

from trading_bot.agents.discovery import DiscoveryAgent
from trading_bot.agents.executor import ExecutorAgent
from trading_bot.agents.researcher import ResearchAgent
from trading_bot.agents.selector import SelectorAgent
from trading_bot.models import ResearchReport, WSEvent, WSEventType
from trading_bot.monitors.base import BaseMonitor
from trading_bot.utils.logging import log


class ResearchAgentMonitor(BaseMonitor):
    """Autonomous stock research pipeline that discovers, scores, allocates, and trades."""

    monitor_type = "research_agent"

    def get_interval_seconds(self) -> int:
        return self.config.research_agent.scan_interval_minutes * 60

    async def run_cycle(self) -> None:
        broker = self.brokers.get("alpaca")
        if not broker:
            log.warning("No Alpaca broker configured for research agent")
            return

        discovery = DiscoveryAgent(self.config)
        researcher = ResearchAgent(self.config)
        selector = SelectorAgent(self.config)
        executor = ExecutorAgent(self.config, broker, self.risk_manager, self.repo)

        # 1. Discovery — find candidates
        log.info(f"Monitor {self.monitor_id}: Starting discovery phase")
        candidates = await discovery.find_candidates()

        # Log discovery run
        await self.repo.insert_discovery_run(
            candidates_json=json.dumps([{"symbol": s, "reason": r} for s, r in candidates]),
            source_queries_json=json.dumps(discovery.source_queries),
            num_candidates=len(candidates),
        )

        # 2. Research — score each candidate (parallel with concurrency limit)
        log.info(f"Monitor {self.monitor_id}: Researching {len(candidates)} candidates")
        sem = asyncio.Semaphore(5)  # Limit concurrent LLM calls

        async def _score(sym: str, reason: str) -> ResearchReport:
            async with sem:
                return await researcher.score(sym, reason)

        reports = await asyncio.gather(
            *[_score(sym, reason) for sym, reason in candidates],
            return_exceptions=True,
        )

        # Filter out exceptions
        valid_reports: list[ResearchReport] = []
        for r in reports:
            if isinstance(r, ResearchReport):
                valid_reports.append(r)
                # Log research report to DB
                await self.repo.insert_research_report(
                    symbol=r.symbol,
                    company_name=r.company_name,
                    sector=r.sector,
                    composite_score=r.composite_score,
                    dimension_scores_json=r.dimension_scores.model_dump_json(),
                    recommendation=r.llm_recommendation,
                    target_weight=r.target_weight,
                    catalysts_json=json.dumps(r.catalysts),
                    risks_json=json.dumps(r.risks),
                )
            elif isinstance(r, Exception):
                log.warning(f"Research failed for a candidate: {r}")

        if not valid_reports:
            log.warning(f"Monitor {self.monitor_id}: No valid research reports")
            return

        # 3. Selection — build target allocation
        log.info(f"Monitor {self.monitor_id}: Building allocation from {len(valid_reports)} reports")
        portfolio = await broker.get_account()
        positions = await broker.get_positions()
        equity = portfolio.equity + portfolio.cash

        allocation = await selector.build_allocation(
            valid_reports, positions, equity
        )

        # Log allocation
        await self.repo.insert_portfolio_allocation(
            entries_json=json.dumps([e.model_dump() for e in allocation.entries]),
            cash_reserve=allocation.cash_reserve,
            rebalance_needed=allocation.rebalance_needed,
            reasoning=allocation.reasoning,
        )

        # 4. Execution — rebalance if needed
        if allocation.rebalance_needed:
            log.info(f"Monitor {self.monitor_id}: Executing rebalance")
            results = await executor.rebalance(allocation, source=f"monitor:{self.monitor_id}")

            for result in results:
                await self.repo.increment_monitor_trade(self.monitor_id)
                await self.event_bus.broadcast(WSEvent(
                    type=WSEventType.TRADE_EXECUTED,
                    data={
                        "symbol": result.symbol,
                        "side": result.side.value,
                        "quantity": result.quantity,
                        "filled_price": result.filled_price,
                        "source": f"monitor:{self.monitor_id}",
                    },
                ))

            log.info(f"Monitor {self.monitor_id}: Rebalance complete, {len(results)} trades")
        else:
            log.info(f"Monitor {self.monitor_id}: No rebalance needed")

        # Broadcast strategy signal
        await self.event_bus.broadcast(WSEvent(
            type=WSEventType.STRATEGY_SIGNAL,
            data={
                "source": f"monitor:{self.monitor_id}",
                "candidates_found": len(candidates),
                "reports_scored": len(valid_reports),
                "rebalance_needed": allocation.rebalance_needed,
                "top_stocks": [
                    {"symbol": r.symbol, "score": r.composite_score, "rec": r.llm_recommendation}
                    for r in sorted(valid_reports, key=lambda x: x.composite_score, reverse=True)[:5]
                ],
            },
        ))
