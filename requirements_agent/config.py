"""Canonical field names shared with the Catalog reader and scorer.

Numeric names end in the unit suffix. Categorical names have unit None
and must use operator "has". Price and lead time are not fields — they
live on RequirementsChecklist.budget_usd / max_lead_time_days.
"""

CANONICAL_FIELDS: dict[str, str | None] = {
    "continuous_torque_nm": "N·m",
    "peak_torque_nm": "N·m",
    "mass_kg": "kg",
    "payload_kg": "kg",
    "supply_voltage_v": "V",
    "power_w": "W",
    "rated_speed_rpm": "rpm",
    "reach_mm": "mm",
    "repeatability_mm": "mm",
    "stroke_mm": "mm",
    "length_mm": "mm",
    "width_mm": "mm",
    "height_mm": "mm",
    "outer_diameter_mm": "mm",
    "grip_force_n": "N",
    "continuous_current_a": "A",
    "bandwidth_hz": "Hz",
    "operating_temp_min_c": "°C",
    "operating_temp_max_c": "°C",
    "frame_rate_hz": "Hz",
    "working_distance_mm": "mm",
    "depth_accuracy_mm": "mm",
    "fov_deg": "°",
    "lidar_range_mm": "mm",
    "angular_resolution_deg": "°",
    "max_speed_mm_s": "mm/s",
    "runtime_h": "h",
    "localization_accuracy_mm": "mm",
    "compute_tops": "TOPS",
    "memory_gb": "GB",
    "comm_interface": None,
    "ip_rating": None,
    "certification": None,
    "cooling": None,
    "feedback": None,
    "drive_type": None,
    "sensing_modality": None,
    "locomotion": None,
    "gripper_type": None,
}

FORBIDDEN_CONSTRAINT_FIELDS = frozenset(
    {"budget_usd", "price_usd", "unit_price_usd", "lead_time_days", "max_lead_time_days"}
)
