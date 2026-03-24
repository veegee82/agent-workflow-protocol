"""Custom risk analysis MCP tool."""
try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    class FastMCP:
        def __init__(self, name): self.name = name
        def tool(self, _name, **kwargs):
            def _d(fn): return fn
            return _d

app = FastMCP("custom")

@app.tool("custom.analyze_risk")
def analyze_risk(*, likelihood: int, impact: int, category: str = "operational") -> dict:
    """Calculate risk score from likelihood and impact ratings.

    Args:
        likelihood: Probability rating (1-5)
        impact: Impact severity rating (1-5)
        category: Risk category (operational, market, credit, compliance)
    """
    likelihood = max(1, min(5, likelihood))
    impact = max(1, min(5, impact))
    risk_score = round((likelihood * impact) / 25.0, 2)

    if risk_score <= 0.3:
        level = "low"
    elif risk_score <= 0.6:
        level = "medium"
    elif risk_score <= 0.8:
        level = "high"
    else:
        level = "critical"

    return {
        "ok": True,
        "status": 200,
        "data": {
            "risk_score": risk_score,
            "level": level,
            "likelihood": likelihood,
            "impact": impact,
            "category": category,
        },
        "error": None,
    }
