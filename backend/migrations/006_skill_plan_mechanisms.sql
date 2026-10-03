ALTER TABLE mechanisms ADD COLUMN review_note TEXT;
CREATE TABLE IF NOT EXISTS skill_plan_mechanisms (
    skill_plan_id TEXT NOT NULL REFERENCES skill_plans(id) ON DELETE CASCADE,
    mechanism_id TEXT NOT NULL REFERENCES mechanisms(id) ON DELETE RESTRICT,
    PRIMARY KEY(skill_plan_id, mechanism_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_plan_mechanisms_mechanism_id ON skill_plan_mechanisms(mechanism_id);
