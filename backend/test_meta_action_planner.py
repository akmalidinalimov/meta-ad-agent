from backend.meta_action_planner import build_action_approval, plan_meta_action


def test_plan_meta_action_detects_campaign_rename():
    plan = plan_meta_action("Rename campaign 120123 to Business Automation VSL - Tashkent")

    assert plan["intent"] == "rename"
    assert plan["target"]["level"] == "campaign"
    assert plan["target"]["id"] == "120123"
    assert plan["after"]["name"] == "Business Automation VSL - Tashkent"
    assert plan["needsClarification"] is False
    assert plan["requiresApproval"] is True


def test_plan_meta_action_detects_budget_change():
    plan = plan_meta_action("Change ad set 9988 budget to $120 per day")

    assert plan["intent"] == "change_budget"
    assert plan["target"]["level"] == "adset"
    assert plan["target"]["id"] == "9988"
    assert plan["after"]["daily_budget_usd"] == 120
    assert plan["risk"] == "medium"


def test_plan_meta_action_marks_ambiguous_pause_request():
    plan = plan_meta_action("Pause the weak ad set")

    assert plan["intent"] == "pause"
    assert plan["needsClarification"] is True
    assert "target object" in plan["clarifyingQuestion"].lower()


def test_build_action_approval_from_rename_plan():
    plan = plan_meta_action("Rename campaign 120123 to Business Automation VSL - Tashkent")

    approval = build_action_approval(plan)

    assert approval["actionType"] == "rename_meta_object"
    assert approval["status"] == "needs_review"
    assert approval["target"]["id"] == "120123"
    assert approval["after"]["name"] == "Business Automation VSL - Tashkent"
    assert approval["executionMethod"] == "api"
