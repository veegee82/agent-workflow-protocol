# Task Manager - File Output Chart

You manage a workflow that generates sine wave data and a matplotlib chart.

## Iteration 1: Delegate the Worker

Delegate ONE worker to generate sine wave data and a chart:

```json
{
  "decision": "delegate",
  "reasoning": "Delegating chart_worker to generate sine wave CSV and PNG chart",
  "delegations": [
    {
      "worker_id": "chart_worker",
      "instructions": "Generate sine wave data and create a chart. Use code.execute to run the following Python code:\n\n1. Generate 100 data points from 0 to 4*pi for a sine wave\n2. Save the data as CSV to `_output_dir + '/sine_data.csv'` with columns: x, sin_x\n3. Create a matplotlib line chart of the sine wave and save as PNG to `_output_dir + '/sine_chart.png'`\n\nIMPORTANT:\n- Use `import matplotlib; matplotlib.use('Agg')` BEFORE importing pyplot (non-interactive backend)\n- Use `import numpy as np` for data generation\n- The CSV should have a header row: x,sin_x\n- The chart should have title 'Sine Wave', xlabel 'x', ylabel 'sin(x)'\n- Return the file paths of both created files",
      "tools_allowed": ["code.execute", "file.write"],
      "output_contract": {
        "csv_path": {"type": "string", "description": "Path to the CSV file"},
        "chart_path": {"type": "string", "description": "Path to the PNG chart"},
        "num_points": {"type": "integer", "description": "Number of data points generated"},
        "confidence": {"type": "number"}
      },
      "codemode": {"enabled": true, "language": "python"}
    }
  ],
  "confidence": 0.3
}
```

## Completion

When the worker returns with file paths and confidence > 0.7, respond with COMPLETE:

```json
{
  "decision": "complete",
  "final_result": {
    "csv_path": "...",
    "chart_path": "...",
    "num_points": 100,
    "confidence": 0.95
  },
  "confidence": 0.95
}
```

## Rules
- Delegate exactly ONE worker
- COMPLETE when worker succeeds with confidence > 0.7
- FAIL if worker fails or files are not created
