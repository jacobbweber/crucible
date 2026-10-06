"""Job dispatch, tool execution, policy, and vault commands."""

import json

from agent_os.cli.context import ReplContext
from agent_os.cli.registry import CommandRegistry, UsageError
from agent_os.domain.policy import ApprovalMode
from agent_os.domain.security import CredentialType


def register(reg: CommandRegistry) -> None:
    @reg.register("job", "Run a background job through the pipeline: /job <task>")
    async def _job(ctx: ReplContext, args: list[str]) -> None:
        if not args:
            raise UsageError("usage: /job <task...>")
        result = await ctx.kernel.execute_job(ctx.session_id, " ".join(args))
        d, env = result.dispatch_result.decision, result.dispatch_result.envelope
        ctx.console.info(
            f"stage={d.stage} recipe={d.matched_recipe_id} score={d.confidence_score} "
            f"tools={d.ephemeral_tools}"
        )
        ctx.console.info(
            f"gap={result.gap_report.resolution_strategy} "
            f"missing={result.gap_report.missing_capabilities} "
            f"graduate={result.flagged_for_graduation}"
        )
        style = "green" if env.status == "completed" else "red"
        ctx.console.write(f"[{env.status}] journey={env.journey_id} {env.duration_ms}ms", style)
        ctx.console.write(env.summary)

    @reg.register("journey", "Show a journey and its scratchpad steps: /journey <id>")
    async def _journey(ctx: ReplContext, args: list[str]) -> None:
        if not args:
            raise UsageError("usage: /journey <journey_id>")
        repo = ctx.kernel.session_repo
        ctx.console.json(repo.get_journey(args[0]))
        for step in repo.get_journey_scratchpad(args[0]):
            ctx.console.write(f"#{step['step_index']} {step['node_name']} ", "cyan", end="")
            ctx.console.write(json.dumps(step["input_payload"]) + " → ", end="")
            ctx.console.write(str(step["output_payload"].get("output", ""))[:300])

    @reg.register("tools", "List registered tools and their action tiers")
    async def _tools(ctx: ReplContext, args: list[str]) -> None:
        for name in sorted(ctx.kernel.tools):
            tier = ctx.kernel._tool_tiers.get(name)
            ctx.console.write(f"  {name:<26} {tier.value if tier else '?'}")

    @reg.register("tool", "Execute a tool via policy+proxy stack: /tool <name> [json-params]")
    async def _tool(ctx: ReplContext, args: list[str]) -> None:
        if not args:
            raise UsageError('usage: /tool <name> \'{"key": "value"}\'')
        params = json.loads(" ".join(args[1:])) if len(args) > 1 else {}
        res = await ctx.kernel.execute_tool(args[0], params)
        style = "green" if res.success else "red"
        ctx.console.write(f"success={res.success}", style)
        ctx.console.write(res.output or res.error or "")

    @reg.register("policy", "Show/set approval mode: /policy [strict|balanced|autonomous]")
    async def _policy(ctx: ReplContext, args: list[str]) -> None:
        gate = ctx.kernel.policy_gate
        if args:
            gate.set_approval_mode(ApprovalMode(args[0]))
        ctx.console.ok(f"approval_mode={gate.approval_mode.value} overrides={gate.overrides}")

    @reg.register("vault", "Vault: /vault add <alias> <type> k=v... | list | rm <alias>")
    async def _vault(ctx: ReplContext, args: list[str]) -> None:
        repo = ctx.kernel.vault_repo
        if not args:
            raise UsageError("usage: /vault add vault://name api_key token=XYZ | list | rm <alias>")
        if args[0] == "add" and len(args) >= 4:
            payload = dict(kv.split("=", 1) for kv in args[3:])
            meta = repo.store_credential(args[1], CredentialType(args[2]), payload)
            ctx.console.ok(f"stored {meta.alias} ({meta.credential_id})")
        elif args[0] == "list":
            ctx.console.json([m.model_dump() for m in repo.list_metadata()])
        elif args[0] == "rm" and len(args) == 2:
            ctx.console.ok(f"deleted={repo.delete_credential(args[1])}")
        else:
            raise UsageError("unknown /vault subcommand")
