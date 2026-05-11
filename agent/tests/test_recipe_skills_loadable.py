"""Verify the three recipe skills are discoverable and well-formed."""

from __future__ import annotations


_RECIPE_SKILLS = {
    "macro-rates-fx-analysis",
    "portfolio-rebalance",
    "equity-fundamental-deep-dive",
    "portfolio-coach",
    "strategy-architect",
}


def test_recipe_skills_are_loaded():
    """SkillsLoader picks up all three recipe SKILL.md files."""
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader()
    names = {s.name for s in loader.skills}
    assert _RECIPE_SKILLS <= names, (
        f"Missing recipe skills: {_RECIPE_SKILLS - names}"
    )


def test_recipe_skills_have_recipe_category():
    """All three skills declare category: recipe in their frontmatter."""
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader()
    by_name = {s.name: s for s in loader.skills}
    for name in _RECIPE_SKILLS:
        assert by_name[name].category == "recipe", (
            f"{name} has category={by_name[name].category!r}, expected 'recipe'"
        )


def test_recipe_category_in_display_order():
    """The 'recipe' category renders before 'other' in grouped output."""
    from src.agent.skills import SkillsLoader

    order = SkillsLoader._CATEGORY_ORDER
    assert "recipe" in order, "_CATEGORY_ORDER missing 'recipe'"
    assert order.index("recipe") < order.index("other"), (
        "'recipe' must render before 'other' in grouped skill display"
    )


def test_recipe_load_skill_returns_full_body():
    """list_skills + load_skill round-trip via the project's helpers."""
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader()
    body = loader.get_content("macro-rates-fx-analysis")
    assert "macro_snapshot" in body, (
        "Recipe body must reference the macro_snapshot tool to be useful"
    )
    assert body.startswith("---") or "When to use" in body, (
        "Recipe body must contain frontmatter or a When-to-use heading"
    )
