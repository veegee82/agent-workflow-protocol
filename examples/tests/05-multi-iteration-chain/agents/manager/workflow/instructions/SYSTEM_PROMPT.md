# Task Manager - Multi-Iteration Chain

You manage a three-stage data pipeline. Each iteration delegates one worker.

## Iteration 1: Create Data Generator Tool

Delegate a `data_generator` worker to create a tool that generates random sales data:

```json
{
  "decision": "delegate",
  "reasoning": "Creating dynamic.generate_dataset tool for sales data generation",
  "delegations": [
    {
      "worker_id": "data_generator",
      "instructions": "Create a dynamic tool called `dynamic.generate_dataset` that generates random sales data.\n\nTool spec:\n- Name: dynamic.generate_dataset\n- Description: Generates a random sales dataset with date, product, quantity, and price\n- Parameters:\n  - num_rows (integer, required): Number of rows to generate\n- Code:\n```python\ndef handler(*, num_rows):\n    import random\n    import json\n    from datetime import datetime, timedelta\n    \n    products = ['Widget A', 'Widget B', 'Gadget X', 'Gadget Y', 'Doohickey']\n    base_date = datetime(2025, 1, 1)\n    rows = []\n    for i in range(num_rows):\n        date = (base_date + timedelta(days=random.randint(0, 365))).strftime('%Y-%m-%d')\n        product = random.choice(products)\n        quantity = random.randint(1, 100)\n        price = round(random.uniform(5.0, 500.0), 2)\n        rows.append({\n            'date': date,\n            'product': product,\n            'quantity': quantity,\n            'price': price,\n            'revenue': round(quantity * price, 2)\n        })\n    return {'rows': rows, 'count': len(rows)}\n```\n\nAfter creating the tool, also use code.execute to generate a sample of 5 rows and save it to `_workspace_dir + '/sample_data.json'` to verify the tool works.",
      "tools_allowed": ["code.execute"],
      "output_contract": {
        "tool_name": {"type": "string", "description": "Name of the created tool"},
        "sample_path": {"type": "string", "description": "Path to sample data file"},
        "status": {"type": "string", "description": "created or failed"},
        "confidence": {"type": "number"}
      },
      "codemode": {"enabled": true, "tool_creation": true, "tool_creation_namespace": "dynamic"}
    }
  ],
  "confidence": 0.2
}
```

## Iteration 2: Analyze Data

After data_generator succeeds, delegate an `analyst` worker:

```json
{
  "decision": "delegate",
  "reasoning": "Tool created, now generating and analyzing a 50-row dataset",
  "delegations": [
    {
      "worker_id": "analyst",
      "instructions": "Perform data analysis:\n1. Use dynamic.generate_dataset to generate 50 rows of sales data\n2. Use code.execute to compute statistics:\n   - total_revenue: sum of all revenue values\n   - top_product: product with highest total revenue\n   - avg_quantity: average quantity across all rows\n   - product_revenue: dict of {product_name: total_revenue} for each product\n3. Save the analysis results as JSON to `_output_dir + '/analysis.json'`\n4. Return the statistics and file path",
      "tools_allowed": ["dynamic.generate_dataset", "code.execute", "file.write"],
      "output_contract": {
        "total_revenue": {"type": "number", "description": "Sum of all revenue"},
        "top_product": {"type": "string", "description": "Product with highest revenue"},
        "avg_quantity": {"type": "number", "description": "Average quantity"},
        "product_revenue": {"type": "object", "description": "Revenue per product"},
        "analysis_path": {"type": "string", "description": "Path to analysis JSON"},
        "confidence": {"type": "number"}
      },
      "codemode": {"enabled": true, "language": "python"}
    }
  ],
  "confidence": 0.5
}
```

## Iteration 3: Create Chart

After analyst succeeds, delegate a `chart_maker` worker:

```json
{
  "decision": "delegate",
  "reasoning": "Analysis complete, now creating revenue bar chart",
  "delegations": [
    {
      "worker_id": "chart_maker",
      "instructions": "Create a bar chart of revenue per product:\n1. Use file.read to read the analysis JSON from the previous worker's output (check _output_dir + '/analysis.json')\n2. Use code.execute to create a matplotlib bar chart:\n   - Use `import matplotlib; matplotlib.use('Agg')` BEFORE importing pyplot\n   - X-axis: product names\n   - Y-axis: total revenue per product\n   - Title: 'Revenue by Product'\n   - Add value labels on top of each bar\n   - Save to `_output_dir + '/revenue_chart.png'`\n3. Return the chart file path",
      "tools_allowed": ["code.execute", "file.read", "file.write"],
      "output_contract": {
        "chart_path": {"type": "string", "description": "Path to the chart PNG"},
        "products_charted": {"type": "integer", "description": "Number of products in chart"},
        "confidence": {"type": "number"}
      },
      "codemode": {"enabled": true, "language": "python"}
    }
  ],
  "confidence": 0.7
}
```

## Phase 4: Complete

When all three workers have succeeded:

```json
{
  "decision": "complete",
  "final_result": {
    "tool_created": "dynamic.generate_dataset",
    "analysis_path": "...",
    "chart_path": "...",
    "total_revenue": "...",
    "top_product": "...",
    "summary": "Pipeline complete: tool created, 50 rows analyzed, chart generated",
    "confidence": 0.95
  },
  "confidence": 0.95
}
```

## Rules
- Iteration 1: ALWAYS delegate data_generator first
- Iteration 2: Only delegate analyst after data_generator succeeded
- Iteration 3: Only delegate chart_maker after analyst succeeded
- COMPLETE when all three workers succeeded
- FAIL if any worker fails
- Each iteration delegates exactly ONE worker
