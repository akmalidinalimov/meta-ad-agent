from backend.strategy_generator import generate_launch_strategy


def sample_playbook():
    return {
        "id": "pb_launch",
        "name": "June AI course launch",
        "goal": "Find quality Telegram START subscribers who can become paid buyers.",
        "primarySuccessMetric": "telegram_start",
        "secondarySuccessMetrics": ["qualified_lead", "purchase"],
        "segments": [
            {
                "id": "income",
                "name": "AI income",
                "targetAudienceNotes": "Full-time employees and second-income seekers",
                "offerAngle": "Earn with AI commercial videos",
                "startingBudgetUsd": 100,
                "locations": ["Uzbekistan"],
                "placements": ["instagram_reels", "instagram_stories", "facebook_feed"],
                "interests": ["Artificial intelligence", "Freelancing"],
                "ageRange": "23-44",
                "gender": "all",
            },
            {
                "id": "business",
                "name": "Business automation",
                "targetAudienceNotes": "Small business owners and SMM agencies",
                "offerAngle": "Use AI to create visuals and automations for clients",
                "startingBudgetUsd": 150,
                "locations": ["Tashkent", "Samarkand"],
                "placements": ["instagram_reels", "instagram_feed"],
                "interests": ["Graphic design", "Digital marketing"],
                "ageRange": "25-45",
                "gender": "all",
                "landingPageUrl": "https://example.com/business",
                "telegramBotUrl": "https://t.me/business_bot",
            },
        ],
        "rules": {
            "startingBudgetUsd": 100,
            "maxDailyBudgetUsd": 500,
            "scalingStepPercent": 20,
            "scalingFrequencyDays": 1,
            "salesCapacityLeadsPerDay": 20,
            "requiresApprovalForExecution": True,
        },
        "alertChannels": ["dashboard", "telegram"],
        "approvalChannels": ["dashboard", "telegram"],
    }


def sample_knowledge():
    return {
        "analysis": {
            "summary": {"spend": 1200, "clicks": 6000, "leads": 1600, "purchases": 0, "cpl": 0.75},
            "placements": [
                {"label": "instagram / reels", "spend": 620, "leads": 900, "purchases": 0, "qualityScore": 67, "cpl": 0.69},
                {"label": "instagram / stories", "spend": 280, "leads": 360, "purchases": 0, "qualityScore": 61, "cpl": 0.78},
                {"label": "facebook / feed", "spend": 180, "leads": 90, "purchases": 0, "qualityScore": 28, "cpl": 2.0},
            ],
            "audience": {
                "ageGender": [
                    {"label": "25-34 / female", "spend": 320, "leads": 440, "qualityScore": 58},
                    {"label": "35-44 / unknown", "spend": 260, "leads": 310, "qualityScore": 54},
                ],
                "regions": [
                    {"label": "Tashkent Region", "spend": 290, "leads": 430, "qualityScore": 62, "cpl": 0.67},
                    {"label": "Fergana", "spend": 90, "leads": 95, "qualityScore": 44, "cpl": 0.95},
                ],
                "interests": [
                    {"label": "Graphic design", "spend": 260, "leads": 330, "qualityScore": 66, "cpl": 0.79},
                    {"label": "Artificial intelligence", "spend": 220, "leads": 260, "qualityScore": 57, "cpl": 0.85},
                ],
            },
            "recommendations": [
                {"area": "Placement", "title": "Scale Instagram Reels", "reason": "Best quality placement."},
            ],
            "lessons": [
                "Cheap clicks alone are not enough; compare against Telegram and CRM quality.",
                "Lead events exist but purchase events are missing or not attributed.",
            ],
        }
    }


def test_generate_launch_strategy_uses_playbook_segments_and_knowledge():
    strategy = generate_launch_strategy(sample_playbook(), sample_knowledge())

    assert strategy["playbookId"] == "pb_launch"
    assert strategy["execution"]["requiresApproval"] is True
    assert strategy["budget"]["totalDailyBudgetUsd"] == 250
    assert [segment["id"] for segment in strategy["segments"]] == ["income", "business"]
    assert strategy["segments"][0]["budgetUsd"] == 100
    assert strategy["segments"][1]["budgetUsd"] == 150
    assert "instagram_reels" in strategy["segments"][0]["recommendedPlacements"]
    assert "facebook_feed" not in strategy["segments"][0]["recommendedPlacements"]
    assert any("Graphic design" in item for item in strategy["segments"][1]["interestStrategy"])
    assert all(action["status"] == "needs_review" for action in strategy["approvalActions"])


def test_generate_launch_strategy_flags_sales_capacity_risk():
    playbook = sample_playbook()
    playbook["rules"]["salesCapacityLeadsPerDay"] = 10

    strategy = generate_launch_strategy(playbook, sample_knowledge())

    assert strategy["budget"]["estimatedDailyLeadLoad"] > 10
    assert any("sales capacity" in risk.lower() for risk in strategy["risks"])


def test_generate_launch_strategy_marks_missing_tracking_links_without_blocking():
    playbook = sample_playbook()
    for segment in playbook["segments"]:
        segment.pop("landingPageUrl", None)
        segment.pop("telegramBotUrl", None)

    strategy = generate_launch_strategy(playbook, sample_knowledge())

    assert {segment["funnelReadiness"]["status"] for segment in strategy["segments"]} == {"needs_links"}
    assert len(strategy["testMatrix"]) >= 3
    assert strategy["assumptions"][0].startswith("Optimize first for")


def test_generate_launch_strategy_filters_non_instagram_noise_from_primary_placement_evidence():
    knowledge = sample_knowledge()
    knowledge["analysis"]["placements"].insert(
        0,
        {"label": "threads / threads_feed", "spend": 900, "leads": 2000, "qualityScore": 80},
    )

    strategy = generate_launch_strategy(sample_playbook(), knowledge)

    assert "threads" not in strategy["summary"].lower()
    assert strategy["knowledgeUsed"]["bestPlacements"][0] == "instagram / reels"
