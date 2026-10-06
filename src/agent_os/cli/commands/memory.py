"""Fact memory and recipe catalog commands."""

from agent_os.cli.context import ReplContext
from agent_os.cli.registry import CommandRegistry, UsageError, make_parser
from agent_os.domain.recipe import RecipeMetadata, RecipeRecord


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def register(reg: CommandRegistry) -> None:
    @reg.register("fact", "Facts: /fact add <entity> <text> | list <entity> | search <q> | rm <id>")
    async def _fact(ctx: ReplContext, args: list[str]) -> None:
        repo = ctx.kernel.facts_repo
        if len(args) < 2:
            raise UsageError("usage: /fact add <entity> <text...> | list <entity> | search <q>")
        sub, rest = args[0], args[1:]
        if sub == "add" and len(rest) >= 2:
            fact = repo.save_fact(entity_key=rest[0], fact_text=" ".join(rest[1:]))
            ctx.console.ok(f"saved {fact.fact_id}")
        elif sub == "list":
            for f in repo.list_by_entity(rest[0]):
                ctx.console.write(f"{f.fact_id}  [{f.entity_key}] {f.fact_text}")
        elif sub == "search":
            for r in repo.search_facts(" ".join(rest)):
                ctx.console.write(f"{r.score:.6f}  [{r.fact.entity_key}] {r.fact.fact_text}")
        elif sub == "rm":
            ctx.console.ok(f"deleted={repo.delete_fact(rest[0])}")
        else:
            raise UsageError("unknown /fact subcommand")

    @reg.register("recall", "Preview fact prefetch for a message: /recall <text>")
    async def _recall(ctx: ReplContext, args: list[str]) -> None:
        payload = ctx.kernel.fact_prefetcher.prefetch_for_turn(" ".join(args))
        ctx.console.info(
            f"recalled={payload.recalled_count} tokens≈{payload.token_estimate} "
            f"keys={payload.matched_entity_keys}"
        )
        ctx.console.write(payload.rendered_block or "(empty)")

    add_parser = make_parser("/recipe add")
    add_parser.add_argument("recipe_id")
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--desc", required=True)
    add_parser.add_argument("--tags", required=True, help="comma-separated")
    add_parser.add_argument("--tools", default="", help="comma-separated")
    add_parser.add_argument(
        "--engine",
        default="react",
        choices=["direct", "react", "plan_execute_verify", "stategraph"],
    )
    add_parser.add_argument("--body", required=True, help="system prompt body")

    @reg.register("recipe", "Recipes: /recipe add ... | list | match <task> | rm <id>")
    async def _recipe(ctx: ReplContext, args: list[str]) -> None:
        repo = ctx.kernel.recipe_repo
        if not args:
            raise UsageError("usage: /recipe add -h | list | match <task> | rm <id>")
        sub, rest = args[0], args[1:]
        if sub == "add":
            ns = add_parser.parse_args(rest)
            meta = RecipeMetadata(
                recipe_id=ns.recipe_id,
                name=ns.name,
                description=ns.desc,
                execution_engine=ns.engine,
                tags=_csv(ns.tags),
                required_tools=_csv(ns.tools),
            )
            repo.upsert_recipe(
                RecipeRecord(metadata=meta, markdown_path=f"repl/{ns.recipe_id}.md", body=ns.body)
            )
            ctx.console.ok(f"upserted recipe {ns.recipe_id}")
        elif sub == "list":
            for r in repo.list_recipes():
                m = r.metadata
                ctx.console.write(f"{m.recipe_id}  {m.name}  engine={m.execution_engine} "
                                  f"tags={m.tags} tools={m.required_tools}")
        elif sub == "match":
            threshold = ctx.kernel.dispatcher.threshold
            ctx.console.dim(f"dispatcher threshold={threshold} (fallback accepts score>0)")
            for match in repo.match_intent(" ".join(rest), limit=5):
                ctx.console.write(f"{match.score:.8f}  {match.recipe.metadata.recipe_id}")
        elif sub == "rm":
            ctx.console.ok(f"deleted={repo.delete_recipe(rest[0])}")
        else:
            raise UsageError("unknown /recipe subcommand")
