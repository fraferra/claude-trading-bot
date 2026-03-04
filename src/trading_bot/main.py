from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from trading_bot.config import load_config, Config
from trading_bot.models import (
    Action, ArbitrageOpportunity, OrderRequest, OrderType, Platform,
    ProbabilityEstimate, Side, TradeDecision,
)

console = Console()


def _get_config(ctx: click.Context) -> Config:
    return ctx.obj["config"]


def _run(coro):
    """Run an async function from sync Click commands."""
    return asyncio.run(coro)


def _build_analyst(config: Config):
    from trading_bot.analysis.llm_analyst import LLMAnalyst
    return LLMAnalyst(config)


def _build_alpaca_broker(config: Config):
    from trading_bot.brokers.alpaca_broker import AlpacaBroker
    return AlpacaBroker(config.alpaca)


def _build_polymarket_broker(config: Config):
    if config.polymarket.paper:
        from trading_bot.brokers.paper_polymarket import PaperPolymarketBroker
        return PaperPolymarketBroker(config.polymarket.paper_balance)
    else:
        from trading_bot.brokers.polymarket_broker import PolymarketBroker
        return PolymarketBroker(config.polymarket)


def _build_risk_manager(config: Config):
    from trading_bot.risk.manager import RiskManager
    return RiskManager(config.risk)


def _build_arb_scanner(config: Config):
    from trading_bot.strategies.arbitrage import ArbitrageScanner
    return ArbitrageScanner(config)


def _build_cross_market_scanner(config: Config):
    from trading_bot.strategies.cross_market import CrossMarketScanner
    return CrossMarketScanner(config)


def _build_probability_edge(config: Config):
    from trading_bot.strategies.probability_edge import ProbabilityEdgeStrategy
    return ProbabilityEdgeStrategy(config)


# --- Display helpers ---

def _display_decision(decision: TradeDecision) -> None:
    color = {"buy": "green", "sell": "red", "hold": "yellow"}.get(decision.action.value, "white")
    confidence_bar = "█" * int(decision.confidence * 20) + "░" * (20 - int(decision.confidence * 20))

    panel_text = (
        f"[bold {color}]{decision.action.value.upper()}[/bold {color}] — {decision.symbol}\n\n"
        f"Confidence: [{color}]{confidence_bar}[/{color}] {decision.confidence:.0%}\n\n"
        f"{decision.reasoning}"
    )

    if decision.suggested_position_pct > 0:
        panel_text += f"\n\nSuggested position: {decision.suggested_position_pct:.1%} of portfolio"
    if decision.suggested_size_usd > 0:
        panel_text += f"\n\nSuggested size: ${decision.suggested_size_usd:,.2f}"

    console.print(Panel(panel_text, title="Analysis Result", border_style=color))


def _display_portfolio(alpaca_summary, poly_summary) -> None:
    table = Table(title="Portfolio Overview", show_lines=True)
    table.add_column("Platform", style="cyan")
    table.add_column("Cash", justify="right")
    table.add_column("Equity", justify="right")
    table.add_column("Daily P&L", justify="right")
    table.add_column("Positions", justify="right")

    if alpaca_summary:
        pnl_color = "green" if alpaca_summary.daily_pnl >= 0 else "red"
        table.add_row(
            "Alpaca (Stocks)",
            f"${alpaca_summary.cash:,.2f}",
            f"${alpaca_summary.equity:,.2f}",
            f"[{pnl_color}]${alpaca_summary.daily_pnl:,.2f}[/{pnl_color}]",
            str(len(alpaca_summary.positions)),
        )

    if poly_summary:
        pnl_color = "green" if poly_summary.daily_pnl >= 0 else "red"
        paper_tag = " (Paper)" if True else ""  # Will be updated based on config
        table.add_row(
            f"Polymarket{paper_tag}",
            f"${poly_summary.cash:,.2f}",
            f"${poly_summary.equity:,.2f}",
            f"[{pnl_color}]${poly_summary.daily_pnl:,.2f}[/{pnl_color}]",
            str(len(poly_summary.positions)),
        )

    console.print(table)

    # Position details
    all_positions = []
    if alpaca_summary:
        all_positions.extend(alpaca_summary.positions)
    if poly_summary:
        all_positions.extend(poly_summary.positions)

    if all_positions:
        pos_table = Table(title="Open Positions")
        pos_table.add_column("Symbol")
        pos_table.add_column("Platform", style="dim")
        pos_table.add_column("Qty", justify="right")
        pos_table.add_column("Avg Entry", justify="right")
        pos_table.add_column("Current", justify="right")
        pos_table.add_column("Value", justify="right")
        pos_table.add_column("P&L", justify="right")

        for p in all_positions:
            pnl_color = "green" if p.unrealized_pnl >= 0 else "red"
            pos_table.add_row(
                p.symbol,
                p.platform.value,
                f"{p.quantity:.4f}",
                f"${p.avg_entry_price:.2f}",
                f"${p.current_price:.2f}",
                f"${p.market_value:.2f}",
                f"[{pnl_color}]${p.unrealized_pnl:.2f}[/{pnl_color}]",
            )

        console.print(pos_table)
    else:
        console.print("[dim]No open positions[/dim]")


def _display_arb_opportunities(opps: list[ArbitrageOpportunity]) -> None:
    if not opps:
        console.print("[yellow]No arbitrage opportunities found.[/yellow]")
        return

    table = Table(title=f"Arbitrage Opportunities ({len(opps)} found)")
    table.add_column("#", style="dim")
    table.add_column("Event")
    table.add_column("Outcomes", justify="right")
    table.add_column("Price Sum", justify="right")
    table.add_column("Net Edge", justify="right", style="green")
    table.add_column("Direction")
    table.add_column("$/Dollar", justify="right")

    for i, opp in enumerate(opps, 1):
        table.add_row(
            str(i),
            opp.event_title[:50],
            str(len(opp.outcomes)),
            f"{opp.price_sum:.4f}",
            f"{opp.edge_pct:.2%}",
            opp.direction,
            f"${opp.estimated_profit_per_dollar:.4f}",
        )

    console.print(table)


def _display_probability_estimate(est: ProbabilityEstimate) -> None:
    edge_color = "green" if est.edge_pct > 0 else "red"
    side_text = est.suggested_side.value.upper() if est.suggested_side else "NONE"
    side_color = "green" if side_text == "BUY" else "red" if side_text == "SELL" else "dim"

    panel_text = (
        f"[bold]{est.question[:80]}[/bold]\n\n"
        f"Market Price:    {est.market_price:.1%}\n"
        f"AI Probability:  {est.ai_probability:.1%}  "
        f"(CI: {est.confidence_interval_low:.0%} – {est.confidence_interval_high:.0%})\n"
        f"Edge:            [{edge_color}]{est.edge_pct:+.1%}[/{edge_color}]\n"
        f"Kelly Fraction:  {est.kelly_fraction:.2%}\n"
        f"Suggested Side:  [{side_color}]{side_text}[/{side_color}]\n\n"
        f"{est.reasoning[:300]}"
    )

    if est.signals_used:
        panel_text += f"\n\n[dim]Signals: {', '.join(est.signals_used[:5])}[/dim]"

    console.print(Panel(panel_text, title="Probability Estimate", border_style=edge_color))


def _display_probability_estimates(estimates: list[ProbabilityEstimate]) -> None:
    if not estimates:
        console.print("[yellow]No probability edge opportunities found.[/yellow]")
        return

    table = Table(title=f"Probability Edge Scan ({len(estimates)} results)")
    table.add_column("#", style="dim")
    table.add_column("Market")
    table.add_column("Market P", justify="right")
    table.add_column("AI P", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("Kelly", justify="right")
    table.add_column("Side")

    for i, est in enumerate(estimates, 1):
        edge_color = "green" if abs(est.edge_pct) >= 0.10 else "yellow"
        side_text = est.suggested_side.value.upper() if est.suggested_side else "—"
        table.add_row(
            str(i),
            est.question[:45],
            f"{est.market_price:.1%}",
            f"{est.ai_probability:.1%}",
            f"[{edge_color}]{est.edge_pct:+.1%}[/{edge_color}]",
            f"{est.kelly_fraction:.2%}",
            side_text,
        )

    console.print(table)


# --- CLI Commands ---

@click.group()
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None) -> None:
    """Claude Trading Bot — LLM-powered stock & prediction market trading."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)

    config = ctx.obj["config"]
    mode = "PAPER" if config.mode == "paper" else "[bold red]LIVE[/bold red]"
    console.print(f"[dim]Mode: {mode} | LLM: {config.llm.model}[/dim]")


@cli.group()
def analyze():
    """Analyze a stock or prediction market with Claude."""
    pass


@analyze.command("stock")
@click.argument("symbol")
@click.pass_context
def analyze_stock(ctx: click.Context, symbol: str) -> None:
    """Analyze a stock and get a trading recommendation."""
    config = _get_config(ctx)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set. Check your .env file.[/red]")
        sys.exit(1)

    symbol = symbol.upper()
    console.print(f"[dim]Analyzing {symbol}...[/dim]")

    async def _run_analysis():
        analyst = _build_analyst(config)

        # Try to get portfolio context from Alpaca
        portfolio = None
        if config.alpaca.api_key:
            try:
                broker = _build_alpaca_broker(config)
                portfolio = await broker.get_account()
            except Exception as e:
                console.print(f"[dim]Could not fetch Alpaca portfolio: {e}[/dim]")

        decision = await analyst.analyze_stock(symbol, portfolio)
        _display_decision(decision)
        return decision

    _run(_run_analysis())


@analyze.command("market")
@click.argument("condition_id")
@click.pass_context
def analyze_market(ctx: click.Context, condition_id: str) -> None:
    """Analyze a Polymarket market and get a trading recommendation."""
    config = _get_config(ctx)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set. Check your .env file.[/red]")
        sys.exit(1)

    console.print(f"[dim]Analyzing market {condition_id}...[/dim]")

    async def _run_analysis():
        analyst = _build_analyst(config)
        broker = _build_polymarket_broker(config)
        portfolio = await broker.get_account()
        decision = await analyst.analyze_polymarket(condition_id, portfolio)
        _display_decision(decision)
        return decision

    _run(_run_analysis())


@cli.group()
def trade():
    """Execute a trade (analyze + confirm + execute)."""
    pass


@trade.command("stock")
@click.argument("symbol")
@click.option("--qty", type=float, default=None, help="Override quantity (default: auto-sized)")
@click.option("--order-type", type=click.Choice(["market", "limit"]), default="market")
@click.option("--limit-price", type=float, default=None)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def trade_stock(ctx: click.Context, symbol: str, qty: float | None, order_type: str, limit_price: float | None, yes: bool) -> None:
    """Analyze a stock, then execute a trade with confirmation."""
    config = _get_config(ctx)
    symbol = symbol.upper()

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)
    if not config.alpaca.api_key:
        console.print("[red]Error: ALPACA_API_KEY not set.[/red]")
        sys.exit(1)

    async def _run_trade():
        analyst = _build_analyst(config)
        broker = _build_alpaca_broker(config)
        risk_mgr = _build_risk_manager(config)
        portfolio = await broker.get_account()

        # Analyze
        console.print(f"[dim]Analyzing {symbol}...[/dim]")
        decision = await analyst.analyze_stock(symbol, portfolio)
        _display_decision(decision)

        if decision.action == Action.HOLD:
            console.print("[yellow]Decision is HOLD — no trade to execute.[/yellow]")
            return

        # Risk check on the decision
        risk_check = risk_mgr.check_decision(decision)
        if not risk_check.approved:
            console.print(f"[red]Risk check failed: {risk_check.reason}[/red]")
            return

        # Determine quantity
        current_price = await broker.get_quote(symbol)
        if qty is not None:
            trade_qty = qty
        else:
            trade_qty = risk_mgr.calculate_position_size(
                decision.confidence, portfolio.equity, current_price
            )

        side = Side.BUY if decision.action == Action.BUY else Side.SELL
        otype = OrderType.LIMIT if order_type == "limit" else OrderType.MARKET

        order = OrderRequest(
            symbol=symbol,
            side=side,
            quantity=trade_qty,
            order_type=otype,
            limit_price=limit_price,
            platform=Platform.ALPACA,
        )

        # Risk check on the order
        order_check = risk_mgr.check_order(order, portfolio, current_price)
        if not order_check.approved:
            console.print(f"[red]Order rejected: {order_check.reason}[/red]")
            return
        if order_check.adjusted_quantity is not None:
            console.print(f"[yellow]{order_check.reason}[/yellow]")
            order.quantity = order_check.adjusted_quantity

        # Confirmation
        console.print(
            f"\n[bold]Order:[/bold] {side.value.upper()} {order.quantity:.4f} {symbol} "
            f"@ {'MARKET' if otype == OrderType.MARKET else f'${limit_price}'} "
            f"(est. ${order.quantity * current_price:,.2f})"
        )

        if not yes:
            if not click.confirm("Execute this trade?"):
                console.print("[dim]Trade cancelled.[/dim]")
                return

        result = await broker.submit_order(order)
        risk_mgr.record_trade()

        status_color = "green" if result.status.value == "filled" else "yellow"
        console.print(
            f"[{status_color}]Order {result.status.value.upper()}[/{status_color}] — "
            f"ID: {result.order_id}"
        )
        if result.filled_price:
            console.print(f"Filled @ ${result.filled_price:.2f}")

    _run(_run_trade())


@trade.command("market")
@click.argument("condition_id")
@click.option("--size", type=float, default=None, help="Override USD size (default: auto-sized)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def trade_market(ctx: click.Context, condition_id: str, size: float | None, yes: bool) -> None:
    """Analyze a Polymarket market, then execute a trade with confirmation."""
    config = _get_config(ctx)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    async def _run_trade():
        analyst = _build_analyst(config)
        broker = _build_polymarket_broker(config)
        risk_mgr = _build_risk_manager(config)
        portfolio = await broker.get_account()

        console.print(f"[dim]Analyzing market {condition_id}...[/dim]")
        decision = await analyst.analyze_polymarket(condition_id, portfolio)
        _display_decision(decision)

        if decision.action == Action.HOLD:
            console.print("[yellow]Decision is HOLD — no trade to execute.[/yellow]")
            return

        risk_check = risk_mgr.check_decision(decision)
        if not risk_check.approved:
            console.print(f"[red]Risk check failed: {risk_check.reason}[/red]")
            return

        # Determine trade size
        current_price = await broker.get_quote(condition_id)
        trade_size_usd = size or decision.suggested_size_usd or 100.0
        trade_qty = trade_size_usd / current_price if current_price > 0 else 0

        side = Side.BUY if decision.action == Action.BUY else Side.SELL

        order = OrderRequest(
            symbol=condition_id,
            side=side,
            quantity=trade_qty,
            order_type=OrderType.MARKET,
            platform=Platform.POLYMARKET,
        )

        order_check = risk_mgr.check_order(order, portfolio, current_price)
        if not order_check.approved:
            console.print(f"[red]Order rejected: {order_check.reason}[/red]")
            return
        if order_check.adjusted_quantity is not None:
            console.print(f"[yellow]{order_check.reason}[/yellow]")
            order.quantity = order_check.adjusted_quantity

        console.print(
            f"\n[bold]Order:[/bold] {side.value.upper()} {order.quantity:.2f} shares "
            f"@ ${current_price:.4f} (≈${order.quantity * current_price:,.2f})"
        )

        if not yes:
            if not click.confirm("Execute this trade?"):
                console.print("[dim]Trade cancelled.[/dim]")
                return

        result = await broker.submit_order(order)
        risk_mgr.record_trade()

        status_color = "green" if result.status.value == "filled" else "yellow"
        console.print(
            f"[{status_color}]Order {result.status.value.upper()}[/{status_color}] — "
            f"ID: {result.order_id}"
        )
        if result.filled_price:
            console.print(f"Filled @ ${result.filled_price:.4f}")

    _run(_run_trade())


@cli.command()
@click.pass_context
def portfolio(ctx: click.Context) -> None:
    """View portfolio across all platforms."""
    config = _get_config(ctx)

    async def _show():
        alpaca_summary = None
        poly_summary = None

        if config.alpaca.api_key:
            try:
                broker = _build_alpaca_broker(config)
                alpaca_summary = await broker.get_account()
            except Exception as e:
                console.print(f"[red]Alpaca error: {e}[/red]")

        try:
            broker = _build_polymarket_broker(config)
            poly_summary = await broker.get_account()
        except Exception as e:
            console.print(f"[red]Polymarket error: {e}[/red]")

        _display_portfolio(alpaca_summary, poly_summary)

    _run(_show())


@cli.group()
def markets():
    """Browse and search Polymarket markets."""
    pass


@markets.command("search")
@click.argument("query")
@click.option("--limit", default=10, help="Max results")
@click.pass_context
def markets_search(ctx: click.Context, query: str, limit: int) -> None:
    """Search for Polymarket markets by keyword."""
    from trading_bot.analysis.market_data import search_polymarket_markets

    async def _search():
        results = await search_polymarket_markets(query, limit)
        if not results:
            console.print("[yellow]No markets found.[/yellow]")
            return

        table = Table(title=f"Polymarket Markets: '{query}'")
        table.add_column("Condition ID", style="dim", max_width=20)
        table.add_column("Question")
        table.add_column("Volume", justify="right")
        table.add_column("End Date", style="dim")

        for m in results:
            cid = m["condition_id"][:18] + "..." if len(m["condition_id"]) > 18 else m["condition_id"]
            table.add_row(
                cid,
                m["question"][:80],
                f"${float(m['volume']):,.0f}" if m["volume"] else "—",
                m.get("end_date", "—")[:10],
            )

        console.print(table)

    _run(_search())


@analyze.command("probability")
@click.argument("condition_id")
@click.pass_context
def analyze_probability(ctx: click.Context, condition_id: str) -> None:
    """Get AI probability estimate for a Polymarket market with Kelly sizing."""
    config = _get_config(ctx)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    console.print(f"[dim]Estimating probability for {condition_id}...[/dim]")

    async def _run_estimate():
        strategy = _build_probability_edge(config)
        broker = _build_polymarket_broker(config)
        portfolio = await broker.get_account()
        estimate = await strategy.analyze_market(condition_id, portfolio)
        _display_probability_estimate(estimate)

    _run(_run_estimate())


# --- Scan commands ---

@cli.group()
def scan():
    """Scan for trading opportunities using automated strategies."""
    pass


@scan.command("arb")
@click.option("--min-edge", type=float, default=None, help="Min edge % (default: from config)")
@click.option("--execute", is_flag=True, help="Execute trades for opportunities found")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation when executing")
@click.pass_context
def scan_arb(ctx: click.Context, min_edge: float | None, execute: bool, yes: bool) -> None:
    """Scan Polymarket events for multi-outcome arbitrage."""
    config = _get_config(ctx)

    async def _run_scan():
        scanner = _build_arb_scanner(config)
        if min_edge is not None:
            scanner.arb_config.min_edge_pct = min_edge

        console.print("[dim]Scanning events for multi-outcome arbitrage...[/dim]")
        result = await scanner.scan()

        opps = [
            ArbitrageOpportunity(**o)
            for o in result.metadata.get("opportunities", [])
        ]
        _display_arb_opportunities(opps)

        meta = result.metadata
        console.print(
            f"\n[dim]Events scanned: {meta.get('events_scanned', 0)} | "
            f"Eligible: {meta.get('eligible_events', 0)} | "
            f"Opportunities: {meta.get('opportunities_found', 0)}[/dim]"
        )

        if execute and result.decisions:
            broker = _build_polymarket_broker(config)
            risk_mgr = _build_risk_manager(config)
            portfolio = await broker.get_account()

            for decision in result.decisions:
                console.print(
                    f"\n[bold]{decision.action.value.upper()} {decision.symbol[:18]}...[/bold] "
                    f"(${decision.suggested_size_usd:,.2f})"
                )
                if not yes:
                    if not click.confirm("Execute?"):
                        continue

                current_price = await broker.get_quote(decision.symbol)
                qty = decision.suggested_size_usd / current_price if current_price > 0 else 0
                order = OrderRequest(
                    symbol=decision.symbol,
                    side=decision.side or Side.BUY,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    platform=Platform.POLYMARKET,
                )
                order_check = risk_mgr.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    console.print(f"[yellow]Skipped: {order_check.reason}[/yellow]")
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                trade_result = await broker.submit_order(order)
                risk_mgr.record_trade()
                console.print(f"[green]Executed: {trade_result.status.value}[/green]")

    _run(_run_scan())


@scan.command("cross-market")
@click.option("-q", "--query", multiple=True, help="Search queries (can repeat)")
@click.option("--execute", is_flag=True, help="Execute trades for opportunities found")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation when executing")
@click.pass_context
def scan_cross_market(ctx: click.Context, query: tuple[str, ...], execute: bool, yes: bool) -> None:
    """Scan for cross-market logical arbitrage using AI."""
    config = _get_config(ctx)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    async def _run_scan():
        scanner = _build_cross_market_scanner(config)
        queries = list(query) if query else None

        console.print("[dim]Scanning for cross-market logical arbitrage...[/dim]")
        result = await scanner.scan(search_queries=queries)

        meta = result.metadata
        console.print(
            f"\n[dim]Markets analyzed: {meta.get('markets_analyzed', 0)} | "
            f"Relationships: {meta.get('relationships_found', 0)} | "
            f"Opportunities: {meta.get('opportunities_found', 0)}[/dim]"
        )

        if result.decisions:
            table = Table(title="Cross-Market Opportunities")
            table.add_column("#", style="dim")
            table.add_column("Action")
            table.add_column("Market", max_width=40)
            table.add_column("Confidence", justify="right")
            table.add_column("Size", justify="right")

            for i, d in enumerate(result.decisions, 1):
                color = "green" if d.action == Action.BUY else "red"
                table.add_row(
                    str(i),
                    f"[{color}]{d.action.value.upper()}[/{color}]",
                    d.symbol[:38],
                    f"{d.confidence:.0%}",
                    f"${d.suggested_size_usd:,.0f}",
                )

            console.print(table)

            for d in result.decisions:
                console.print(f"\n[dim]{d.reasoning}[/dim]")
        else:
            console.print("[yellow]No cross-market opportunities found.[/yellow]")

        if execute and result.decisions:
            broker = _build_polymarket_broker(config)
            risk_mgr = _build_risk_manager(config)
            portfolio = await broker.get_account()

            for decision in result.decisions:
                console.print(
                    f"\n[bold]{decision.action.value.upper()} {decision.symbol[:18]}...[/bold]"
                )
                if not yes:
                    if not click.confirm("Execute?"):
                        continue

                current_price = await broker.get_quote(decision.symbol)
                qty = decision.suggested_size_usd / current_price if current_price > 0 else 0
                order = OrderRequest(
                    symbol=decision.symbol,
                    side=decision.side or Side.BUY,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    platform=Platform.POLYMARKET,
                )
                order_check = risk_mgr.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    console.print(f"[yellow]Skipped: {order_check.reason}[/yellow]")
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                trade_result = await broker.submit_order(order)
                risk_mgr.record_trade()
                console.print(f"[green]Executed: {trade_result.status.value}[/green]")

    _run(_run_scan())


@scan.command("probability")
@click.option("-q", "--query", default=None, help="Search query to find markets")
@click.option("--condition-ids", default=None, help="Comma-separated condition IDs")
@click.option("--execute", is_flag=True, help="Execute trades for edge opportunities")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation when executing")
@click.pass_context
def scan_probability(ctx: click.Context, query: str | None, condition_ids: str | None, execute: bool, yes: bool) -> None:
    """Scan markets for AI probability edge opportunities."""
    config = _get_config(ctx)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    async def _run_scan():
        strategy = _build_probability_edge(config)
        broker = _build_polymarket_broker(config)
        portfolio = await broker.get_account()

        ids = condition_ids.split(",") if condition_ids else None

        console.print("[dim]Scanning markets for probability edge...[/dim]")
        result = await strategy.scan(
            condition_ids=ids,
            search_query=query,
            portfolio=portfolio,
        )

        estimates = [
            ProbabilityEstimate(**e)
            for e in result.metadata.get("estimates", [])
        ]
        _display_probability_estimates(estimates)

        if execute and result.decisions:
            risk_mgr = _build_risk_manager(config)

            for decision in result.decisions:
                console.print(
                    f"\n[bold]{decision.action.value.upper()} {decision.symbol[:18]}...[/bold] "
                    f"(${decision.suggested_size_usd:,.2f}, Kelly: {decision.confidence:.0%})"
                )
                if not yes:
                    if not click.confirm("Execute?"):
                        continue

                current_price = await broker.get_quote(decision.symbol)
                qty = decision.suggested_size_usd / current_price if current_price > 0 else 0
                order = OrderRequest(
                    symbol=decision.symbol,
                    side=decision.side or Side.BUY,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    platform=Platform.POLYMARKET,
                )
                order_check = risk_mgr.check_order(order, portfolio, current_price)
                if not order_check.approved:
                    console.print(f"[yellow]Skipped: {order_check.reason}[/yellow]")
                    continue
                if order_check.adjusted_quantity is not None:
                    order.quantity = order_check.adjusted_quantity

                trade_result = await broker.submit_order(order)
                risk_mgr.record_trade()
                console.print(f"[green]Executed: {trade_result.status.value}[/green]")

    _run(_run_scan())


@cli.group("config")
def config_group():
    """View or modify configuration."""
    pass


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Display current configuration."""
    config = _get_config(ctx)

    table = Table(title="Current Configuration", show_lines=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Mode", config.mode.upper())
    table.add_row("LLM Model", config.llm.model)
    table.add_row("LLM Max Tokens", str(config.llm.max_tokens))
    table.add_row("", "")
    table.add_row("Alpaca Paper", str(config.alpaca.paper))
    table.add_row("Alpaca API Key", "***" + config.alpaca.api_key[-4:] if config.alpaca.api_key else "[red]NOT SET[/red]")
    table.add_row("Alpaca Data Feed", config.alpaca.data_feed)
    table.add_row("", "")
    table.add_row("Polymarket Paper", str(config.polymarket.paper))
    table.add_row("Polymarket Paper Balance", f"${config.polymarket.paper_balance:,.2f}")
    table.add_row("", "")
    table.add_row("Max Position %", f"{config.risk.max_position_pct:.0%}")
    table.add_row("Max Exposure %", f"{config.risk.max_total_exposure_pct:.0%}")
    table.add_row("Daily Loss Limit %", f"{config.risk.daily_loss_limit_pct:.0%}")
    table.add_row("Min Confidence", f"{config.risk.min_confidence:.0%}")
    table.add_row("Max Trades/Day", str(config.risk.max_trades_per_day))
    table.add_row("", "")
    table.add_row("Stock Watchlist", ", ".join(config.stocks.watchlist))
    table.add_row("Default Period", config.stocks.default_period)
    table.add_row("", "")
    table.add_row("Run Interval", f"{config.run.interval_minutes} min")
    table.add_row("Auto Execute", str(config.run.auto_execute))
    table.add_row("", "")
    table.add_row("[bold]Arbitrage Strategy[/bold]", "")
    table.add_row("Min Edge %", f"{config.strategies.arbitrage.min_edge_pct:.1%}")
    table.add_row("Fee Estimate %", f"{config.strategies.arbitrage.fee_estimate_pct:.1%}")
    table.add_row("Max Events", str(config.strategies.arbitrage.max_events_to_scan))
    table.add_row("Max Size/Leg", f"${config.strategies.arbitrage.max_size_per_leg_usd:,.0f}")
    table.add_row("", "")
    table.add_row("[bold]Cross-Market Strategy[/bold]", "")
    table.add_row("Min Edge %", f"{config.strategies.cross_market.min_edge_pct:.1%}")
    table.add_row("Max Pairs", str(config.strategies.cross_market.max_pairs_to_analyze))
    table.add_row("Max Size", f"${config.strategies.cross_market.max_size_usd:,.0f}")
    table.add_row("", "")
    table.add_row("[bold]Probability Edge Strategy[/bold]", "")
    table.add_row("Min Edge %", f"{config.strategies.probability_edge.min_edge_pct:.1%}")
    table.add_row("Kelly Cap", f"{config.strategies.probability_edge.kelly_fraction_cap:.0%}")
    table.add_row("Max Size", f"${config.strategies.probability_edge.max_size_usd:,.0f}")

    console.print(table)


# --- Research Agent Commands ---

@cli.group("research")
def research():
    """Autonomous stock research agent commands."""
    pass


@research.command("run")
@click.pass_context
def research_run(ctx: click.Context) -> None:
    """Run the full research pipeline: discover → research → allocate → execute."""
    config = _get_config(ctx)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    async def _run_pipeline():
        from trading_bot.agents.discovery import DiscoveryAgent
        from trading_bot.agents.researcher import ResearchAgent
        from trading_bot.agents.selector import SelectorAgent

        discovery = DiscoveryAgent(config)
        researcher = ResearchAgent(config)
        selector = SelectorAgent(config)

        # 1. Discovery
        console.print("[bold]Phase 1: Discovery[/bold]")
        candidates = await discovery.find_candidates()

        table = Table(title=f"Candidates ({len(candidates)})")
        table.add_column("Symbol", style="cyan")
        table.add_column("Reason")
        for sym, reason in candidates:
            table.add_row(sym, reason[:80])
        console.print(table)

        # 2. Research
        console.print("\n[bold]Phase 2: Research[/bold]")
        reports = []
        for sym, reason in candidates:
            try:
                console.print(f"  [dim]Scoring {sym}...[/dim]")
                report = await researcher.score(sym, reason)
                reports.append(report)
            except Exception as e:
                console.print(f"  [red]Failed: {sym}: {e}[/red]")

        reports.sort(key=lambda r: r.composite_score, reverse=True)

        table = Table(title=f"Research Reports ({len(reports)})")
        table.add_column("Symbol", style="cyan")
        table.add_column("Score", justify="right")
        table.add_column("Rec")
        table.add_column("Sector", style="dim")
        table.add_column("Weight", justify="right")
        for r in reports:
            color = "green" if r.composite_score >= 7 else "yellow" if r.composite_score >= 5 else "red"
            table.add_row(
                r.symbol,
                f"[{color}]{r.composite_score:.1f}[/{color}]",
                r.llm_recommendation,
                r.sector[:15],
                f"{r.target_weight:.1%}",
            )
        console.print(table)

        # 3. Allocation
        console.print("\n[bold]Phase 3: Allocation[/bold]")
        positions = []
        equity = 100000.0  # Default for display
        if config.alpaca.api_key:
            try:
                broker = _build_alpaca_broker(config)
                portfolio = await broker.get_account()
                positions = portfolio.positions
                equity = portfolio.equity + portfolio.cash
            except Exception:
                pass

        allocation = await selector.build_allocation(reports, positions, equity)

        table = Table(title="Target Allocation")
        table.add_column("Symbol", style="cyan")
        table.add_column("Target %", justify="right")
        table.add_column("Current %", justify="right")
        table.add_column("Score", justify="right")
        table.add_column("Action")
        for e in allocation.entries:
            color = {"buy": "green", "add": "green", "sell": "red", "trim": "red"}.get(e.action, "yellow")
            table.add_row(
                e.symbol,
                f"{e.target_weight:.1%}",
                f"{e.current_weight:.1%}",
                f"{e.research_score:.1f}",
                f"[{color}]{e.action.upper()}[/{color}]",
            )
        console.print(table)
        console.print(f"\n[dim]Cash reserve: {allocation.cash_reserve:.1%} | Rebalance needed: {allocation.rebalance_needed}[/dim]")
        console.print(f"[dim]{allocation.reasoning}[/dim]")

    _run(_run_pipeline())


@research.command("status")
@click.pass_context
def research_status(ctx: click.Context) -> None:
    """Show research agent configuration and last run info."""
    config = _get_config(ctx)
    ra = config.research_agent

    table = Table(title="Research Agent Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Enabled", str(ra.enabled))
    table.add_row("Scan Interval", f"{ra.scan_interval_minutes} min")
    table.add_row("Max Candidates", str(ra.max_candidates))
    table.add_row("Max Positions", str(ra.max_positions))
    table.add_row("Max Single Position", f"{ra.max_single_position_pct:.0%}")
    table.add_row("Min Cash Reserve", f"{ra.min_cash_reserve_pct:.0%}")
    table.add_row("Rebalance Threshold", f"{ra.rebalance_drift_threshold:.0%}")
    table.add_row("Min Research Score", str(ra.min_research_score))
    table.add_row("Strategy Review Day", ra.strategy_review_day)

    console.print(table)


@cli.command("serve")
@click.option("--host", default=None, help="Host to bind (default: from config)")
@click.option("--port", type=int, default=None, help="Port to bind (default: from config)")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.pass_context
def serve(ctx: click.Context, host: str | None, port: int | None, reload: bool) -> None:
    """Start the web dashboard and API server."""
    import uvicorn
    from trading_bot.api.app import create_app

    config = _get_config(ctx)
    h = host or config.server.host
    p = port or config.server.port

    console.print(f"[bold]Starting web server[/bold] at http://{h}:{p}")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    app = create_app(config)
    uvicorn.run(app, host=h, port=p, reload=reload)


@cli.command("run")
@click.option("--interval", type=int, default=None, help="Minutes between analysis runs")
@click.option("--stocks-only", is_flag=True, help="Only analyze stocks")
@click.pass_context
def run_loop(ctx: click.Context, interval: int | None, stocks_only: bool) -> None:
    """Run continuous analysis loop on watchlist."""
    config = _get_config(ctx)
    interval = interval or config.run.interval_minutes

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    console.print(f"[bold]Starting analysis loop[/bold] (interval: {interval}min, auto-execute: {config.run.auto_execute})")
    console.print(f"[dim]Watchlist: {', '.join(config.stocks.watchlist)}[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    async def _loop():
        analyst = _build_analyst(config)
        risk_mgr = _build_risk_manager(config)

        alpaca_broker = None
        if config.alpaca.api_key:
            alpaca_broker = _build_alpaca_broker(config)

        while True:
            try:
                console.rule(f"[bold]Analysis Run")

                # Analyze watchlist stocks
                for symbol in config.stocks.watchlist:
                    try:
                        portfolio = None
                        if alpaca_broker:
                            portfolio = await alpaca_broker.get_account()

                        decision = await analyst.analyze_stock(symbol, portfolio)
                        _display_decision(decision)

                        if decision.action != Action.HOLD and config.run.auto_execute:
                            risk_check = risk_mgr.check_decision(decision)
                            if risk_check.approved and alpaca_broker and portfolio:
                                current_price = await alpaca_broker.get_quote(symbol)
                                trade_qty = risk_mgr.calculate_position_size(
                                    decision.confidence, portfolio.equity, current_price
                                )
                                order = OrderRequest(
                                    symbol=symbol,
                                    side=Side.BUY if decision.action == Action.BUY else Side.SELL,
                                    quantity=trade_qty,
                                    order_type=OrderType.MARKET,
                                    platform=Platform.ALPACA,
                                )
                                order_check = risk_mgr.check_order(order, portfolio, current_price)
                                if order_check.approved:
                                    if order_check.adjusted_quantity:
                                        order.quantity = order_check.adjusted_quantity
                                    result = await alpaca_broker.submit_order(order)
                                    risk_mgr.record_trade()
                                    console.print(f"[green]Auto-executed: {result.status.value}[/green]")
                                else:
                                    console.print(f"[yellow]Skipped: {order_check.reason}[/yellow]")
                            elif not risk_check.approved:
                                console.print(f"[yellow]Skipped: {risk_check.reason}[/yellow]")

                    except Exception as e:
                        console.print(f"[red]Error analyzing {symbol}: {e}[/red]")

                console.print(f"\n[dim]Next run in {interval} minutes...[/dim]\n")
                await asyncio.sleep(interval * 60)

            except KeyboardInterrupt:
                console.print("\n[dim]Stopping analysis loop.[/dim]")
                break

    try:
        _run(_loop())
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


if __name__ == "__main__":
    cli()
