"""Static demo / fallback dashboard dataset.

Used by the /api/dashboard endpoint when no real Meta knowledge base has been
synced yet. Pure data with no logic; extracted from app.py so the web layer
stays focused on routing and orchestration.
"""

campaigns = [
    {
        "id": "cmp_ai_course_may_2026",
        "platform": "meta",
        "name": "AI Course Webinar - May 2026",
        "objective": "sales",
        "status": "active",
        "dailyBudgetUsd": 220,
        "startedAt": "2026-05-01",
    }
]

ad_sets = [
    {
        "id": "as_women_25_34",
        "campaignId": "cmp_ai_course_may_2026",
        "name": "Women 25-34 - AI income interest",
        "status": "active",
        "ageMin": 25,
        "ageMax": 34,
        "genders": ["female"],
        "locations": ["Uzbekistan"],
        "interests": ["Artificial intelligence", "Online education", "Freelancing"],
        "placements": ["instagram_reels", "instagram_stories"],
        "optimizationGoal": "conversion",
    },
    {
        "id": "as_women_35_44",
        "campaignId": "cmp_ai_course_may_2026",
        "name": "Women 35-44 - high intent",
        "status": "active",
        "ageMin": 35,
        "ageMax": 44,
        "genders": ["female"],
        "locations": ["Uzbekistan"],
        "interests": ["Business education", "Digital marketing", "Online courses"],
        "placements": ["instagram_reels", "instagram_feed", "facebook_reels"],
        "optimizationGoal": "purchase",
    },
    {
        "id": "as_young_broad",
        "campaignId": "cmp_ai_course_may_2026",
        "name": "Women 18-24 - broad creative test",
        "status": "active",
        "ageMin": 18,
        "ageMax": 24,
        "genders": ["female"],
        "locations": ["Uzbekistan"],
        "interests": ["Artificial intelligence", "ChatGPT", "Content creation"],
        "placements": ["instagram_reels", "facebook_feed", "audience_network"],
        "optimizationGoal": "lead",
    },
]

ads = [
    {"id": "ad_housewife_cartoon", "adSetId": "as_young_broad", "creativeId": "cr_housewife_cartoon", "name": "Housewife AI Cartoon", "status": "active"},
    {"id": "ad_income_case_study", "adSetId": "as_women_35_44", "creativeId": "cr_income_case_study", "name": "AI Income Case Study", "status": "active"},
    {"id": "ad_student_before_after", "adSetId": "as_women_25_34", "creativeId": "cr_student_before_after", "name": "Student Before/After", "status": "active"},
    {"id": "ad_ai_tool_montage", "adSetId": "as_women_25_34", "creativeId": "cr_ai_tool_montage", "name": "AI Tool Montage", "status": "active"},
]

creatives = [
    {"id": "cr_housewife_cartoon", "adId": "ad_housewife_cartoon", "name": "Housewife AI Cartoon", "format": "video", "theme": "Humor / relatable", "hookType": "Comedic identity hook", "primaryPersona": "Non-working female housewife", "cta": "Join free AI webinar"},
    {"id": "cr_income_case_study", "adId": "ad_income_case_study", "name": "AI Income Case Study", "format": "video", "theme": "Proof / webinar", "hookType": "Outcome proof", "primaryPersona": "Adult learner with income intent", "cta": "Reserve webinar seat"},
    {"id": "cr_student_before_after", "adId": "ad_student_before_after", "name": "Student Before/After", "format": "video", "theme": "Transformation", "hookType": "Before and after", "primaryPersona": "Beginner AI student", "cta": "Start learning AI"},
    {"id": "cr_ai_tool_montage", "adId": "ad_ai_tool_montage", "name": "AI Tool Montage", "format": "video", "theme": "Feature demo", "hookType": "Fast tool reveal", "primaryPersona": "AI-curious creator", "cta": "See the tools in class"},
]

creative_analyses = [
    {
        "creativeId": "cr_housewife_cartoon",
        "viralScore": 94,
        "buyerIntentScore": 31,
        "courseFitScore": 42,
        "purchasingPowerScore": 28,
        "funnelQualityScore": 36,
        "hookSummary": "Relatable humor gets attention quickly.",
        "conversionRisk": "Audience may consume it as entertainment instead of a paid learning path.",
        "recommendedAction": "Retool message",
        "sceneNotes": [
            "First seconds use exaggerated facial expression and household context.",
            "Middle section creates comedy but does not establish course value.",
            "CTA arrives after the joke, so buyer intent is weak.",
        ],
        "whyItWorked": "The setup feels familiar and easy to share, so it earns cheap attention.",
        "whyItDidNotConvert": "The viewer is entertained before they are qualified for a paid AI course.",
    },
    {
        "creativeId": "cr_income_case_study",
        "viralScore": 64,
        "buyerIntentScore": 88,
        "courseFitScore": 92,
        "purchasingPowerScore": 84,
        "funnelQualityScore": 89,
        "hookSummary": "Proof-led intro qualifies viewers early.",
        "conversionRisk": "May need more emotional contrast to scale.",
        "recommendedAction": "Scale carefully",
        "sceneNotes": [
            "Opening promise is specific and tied to income outcome.",
            "Proof segment gives the audience a reason to trust the webinar.",
            "CTA aligns with the course offer and attracts fewer low-intent clicks.",
        ],
        "whyItWorked": "The creative filters for people who want practical AI income skills.",
        "whyItDidNotConvert": "It may feel less entertaining at cold scale, so hook variety is needed.",
    },
    {
        "creativeId": "cr_student_before_after",
        "viralScore": 71,
        "buyerIntentScore": 79,
        "courseFitScore": 86,
        "purchasingPowerScore": 76,
        "funnelQualityScore": 81,
        "hookSummary": "Transformation is clear and course-aligned.",
        "conversionRisk": "Needs stronger urgency for webinar attendance.",
        "recommendedAction": "Duplicate test",
        "sceneNotes": [
            "Before/after contrast is easy to understand.",
            "Learning path is visible, which improves course fit.",
            "The CTA could be moved earlier for better webinar show-up.",
        ],
        "whyItWorked": "It shows a believable path from beginner to capable AI user.",
        "whyItDidNotConvert": "The next action is not urgent enough for some viewers.",
    },
    {
        "creativeId": "cr_ai_tool_montage",
        "viralScore": 82,
        "buyerIntentScore": 48,
        "courseFitScore": 61,
        "purchasingPowerScore": 46,
        "funnelQualityScore": 52,
        "hookSummary": "Fast visuals pull clicks from AI-curious viewers.",
        "conversionRisk": "Feature curiosity is weaker than purchase intent.",
        "recommendedAction": "Add offer clarity",
        "sceneNotes": [
            "Rapid tool switching creates attention and novelty.",
            "The course connection is implied instead of stated.",
            "A clearer transformation would help qualify paid learners.",
        ],
        "whyItWorked": "Tool reveals create curiosity and high click volume.",
        "whyItDidNotConvert": "Curiosity about tools does not automatically mean readiness to buy a course.",
    },
]

metrics = [
    {"date": "2026-05-01", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_young_broad", "adId": "ad_housewife_cartoon", "creativeId": "cr_housewife_cartoon", "placement": "instagram_reels", "spendUsd": 118, "impressions": 62000, "clicks": 2600, "landingPageViews": 2070, "leads": 420, "telegramSubscribers": 238, "webinarAttendees": 52, "purchases": 2, "purchaseRevenueUsd": 460},
    {"date": "2026-05-04", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "instagram_stories", "spendUsd": 132, "impressions": 51000, "clicks": 920, "landingPageViews": 812, "leads": 132, "telegramSubscribers": 88, "webinarAttendees": 31, "purchases": 4, "purchaseRevenueUsd": 920},
    {"date": "2026-05-07", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_25_34", "adId": "ad_student_before_after", "creativeId": "cr_student_before_after", "placement": "instagram_reels", "spendUsd": 156, "impressions": 74000, "clicks": 1840, "landingPageViews": 1450, "leads": 284, "telegramSubscribers": 164, "webinarAttendees": 44, "purchases": 5, "purchaseRevenueUsd": 1150},
    {"date": "2026-05-10", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_25_34", "adId": "ad_ai_tool_montage", "creativeId": "cr_ai_tool_montage", "placement": "facebook_feed", "spendUsd": 171, "impressions": 83000, "clicks": 3120, "landingPageViews": 2290, "leads": 438, "telegramSubscribers": 214, "webinarAttendees": 39, "purchases": 3, "purchaseRevenueUsd": 690},
    {"date": "2026-05-13", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "instagram_reels", "spendUsd": 188, "impressions": 68500, "clicks": 1260, "landingPageViews": 1010, "leads": 194, "telegramSubscribers": 126, "webinarAttendees": 43, "purchases": 6, "purchaseRevenueUsd": 1380},
    {"date": "2026-05-16", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "facebook_reels", "spendUsd": 205, "impressions": 72000, "clicks": 1320, "landingPageViews": 1090, "leads": 212, "telegramSubscribers": 141, "webinarAttendees": 50, "purchases": 7, "purchaseRevenueUsd": 1610},
    {"date": "2026-05-19", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_young_broad", "adId": "ad_housewife_cartoon", "creativeId": "cr_housewife_cartoon", "placement": "audience_network", "spendUsd": 218, "impressions": 104000, "clicks": 3640, "landingPageViews": 2510, "leads": 510, "telegramSubscribers": 244, "webinarAttendees": 36, "purchases": 4, "purchaseRevenueUsd": 920},
    {"date": "2026-05-21", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "instagram_reels", "spendUsd": 226, "impressions": 67500, "clicks": 1280, "landingPageViews": 1110, "leads": 228, "telegramSubscribers": 151, "webinarAttendees": 61, "purchases": 8, "purchaseRevenueUsd": 1840},
]

audience = [
    {"segment": "25-34 Women", "spend": 1180, "subs": 352, "buyers": 21},
    {"segment": "35-44 Women", "spend": 920, "subs": 246, "buyers": 28},
    {"segment": "18-24 Women", "spend": 760, "subs": 390, "buyers": 5},
    {"segment": "AI Interest Broad", "spend": 1240, "subs": 281, "buyers": 13},
    {"segment": "Retarget 30D", "spend": 720, "subs": 113, "buyers": 7},
]

insights = [
    {"icon": "trendingDown", "title": "Viral traffic is not buyer traffic", "body": "The cartoon housewife creative is winning clicks but losing after Telegram. Keep the hook, but qualify viewers with course value before second 6.", "tone": "warning"},
    {"icon": "target", "title": "35-44 women show stronger purchasing power", "body": "This group has fewer clicks than 18-24, but 4.2x stronger buyer rate. Shift the next test toward intent and proof-based creative.", "tone": "good"},
    {"icon": "alert", "title": "Facebook Feed is leaking budget", "body": "FB Feed uses 18% of spend but produces 5% of buyers. Keep it for retargeting only until cold performance improves.", "tone": "danger"},
]

experiments = [
    {"title": "Retool viral cartoon into buyer-intent version", "metric": "Qualified Telegram subscriber below $3.50", "budget": "$45/day for 3 days"},
    {"title": "Scale proof-led case study creative", "metric": "Cost per buyer below $58", "budget": "$70/day with 20% daily cap"},
    {"title": "Placement split: IG Reels vs IG Stories", "metric": "Webinar attendance rate above 28%", "budget": "$30/day per placement"},
]

tracking_health = [
    {"name": "Meta Pixel", "status": "healthy", "matchRate": 94, "lastEventAt": "2026-05-21 18:42", "note": "Browser events are arriving from the landing page."},
    {"name": "Conversions API", "status": "healthy", "matchRate": 91, "lastEventAt": "2026-05-21 18:40", "note": "Server events are matching pixel events with stable deduplication."},
    {"name": "Landing Page Lead Form", "status": "warning", "matchRate": 78, "lastEventAt": "2026-05-21 18:15", "note": "Visit-to-lead rate dropped on mobile traffic."},
    {"name": "Telegram Bot Start", "status": "healthy", "matchRate": 88, "lastEventAt": "2026-05-21 18:33", "note": "Subscriber attribution is preserving campaign and creative IDs."},
    {"name": "Webinar Attendance", "status": "warning", "matchRate": 72, "lastEventAt": "2026-05-21 17:50", "note": "Attendance import is delayed and should be monitored."},
    {"name": "Purchase Events", "status": "healthy", "matchRate": 86, "lastEventAt": "2026-05-21 18:11", "note": "Buyer events include value and source attribution."},
]

approval_actions = [
    {"id": "act_pause_fb_feed_cold", "title": "Move Facebook Feed out of cold campaigns", "impact": "Reduce spend leakage from low-buyer traffic.", "risk": "medium", "owner": "human", "status": "needs_review"},
    {"id": "act_scale_case_study", "title": "Increase case study budget by 20%", "impact": "Give strongest buyer-intent creative more delivery.", "risk": "low", "owner": "agent", "status": "ready"},
    {"id": "act_retool_cartoon", "title": "Create buyer-intent version of cartoon creative", "impact": "Keep viral hook while qualifying course buyers earlier.", "risk": "low", "owner": "human", "status": "ready"},
    {"id": "act_check_mobile_landing", "title": "Audit mobile landing page lead drop", "impact": "Recover lost leads before scaling budget.", "risk": "high", "owner": "human", "status": "blocked"},
]

glossary = [
    {"metric": "Qualified Telegram Subscriber", "definition": "A subscriber attributed to an ad who joins Telegram and shows a quality signal such as staying, clicking, or webinar intent.", "watchFor": "If this rises while clicks stay cheap, the creative may be attracting the wrong audience."},
    {"metric": "Landing Visit Rate", "definition": "Landing page views divided by ad clicks.", "watchFor": "A drop often means slow page load, broken tracking, or click quality issues."},
    {"metric": "Buyer Intent Score", "definition": "Creative analysis score estimating whether the message attracts people likely to pay for AI courses.", "watchFor": "High viral score with low buyer intent is a warning sign."},
    {"metric": "Funnel Quality Score", "definition": "Combined score from lead rate, Telegram join rate, webinar attendance, and purchases.", "watchFor": "Use this to decide what to scale, not CTR alone."},
    {"metric": "Placement Waste", "definition": "A placement that spends materially more than its buyer contribution.", "watchFor": "Cold campaigns should not keep placements that spend but do not produce buyers."},
]
