{
  "hardware": ["3D depth camera", "robot arm", "gripper"],
  "software": ["6D pose estimation", "bin segmentation", "grasp planning", "collision-free motion planning"],
  "checklists": [
    {
      "problem_statement": "<raw user text>",
      "component_type": "3D depth camera",
      "search_terms": ["3D depth camera", "RGB-D camera", "structured light camera", "time of flight camera"],
      "software": ["6D pose estimation", "bin segmentation"],
      "must_have": [
        {"field": "sensing_modality", "operator": "has", "value": "RGB-D", "unit": null},
        {"field": "working_distance_mm", "operator": ">=", "value": 400, "unit": "mm"},
        {"field": "depth_accuracy_mm", "operator": "<=", "value": 2, "unit": "mm"},
        {"field": "frame_rate_hz", "operator": ">=", "value": 15, "unit": "Hz"}
      ],
      "nice_to_have": [],
      "budget_usd": 3000,
      "max_lead_time_days": 30,
      "ship_to": "US",
      "quantity": 1,
      "assumptions": ["Paired software: 6D pose estimation, bin segmentation", "Working distance inferred for tote picking"]
    }
  ]
}
