CREATE TABLE IF NOT EXISTS user_profile (
  user_id TEXT PRIMARY KEY,
  likes TEXT,
  dislikes TEXT,
  pace TEXT,
  budget_style TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS task_history (
  task_id TEXT PRIMARY KEY,
  user_id TEXT,
  user_input TEXT,
  final_plan TEXT,
  feedback TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS plan_feedback (
  feedback_id TEXT PRIMARY KEY,
  task_id TEXT,
  trace_id TEXT,
  user_id TEXT,
  rating INTEGER,
  tags TEXT,
  note TEXT,
  item_feedback TEXT,
  learned_preferences TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS memory_events (
  event_id TEXT PRIMARY KEY,
  user_id TEXT,
  source_task_id TEXT,
  source_trace_id TEXT,
  event_type TEXT,
  content TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_trace (
  trace_id TEXT,
  step_index INTEGER,
  node_name TEXT,
  input_json TEXT,
  output_json TEXT,
  latency_ms INTEGER,
  status TEXT,
  created_at TEXT
);
