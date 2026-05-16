-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create Doctors table
CREATE TABLE IF NOT EXISTS doctors (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    specialty VARCHAR(255) NOT NULL,
    embedding vector(1024), -- BAAI/bge-m3 (EMBED_MODEL default)
    schedule_start TIME NOT NULL DEFAULT '09:00:00',
    schedule_end TIME NOT NULL DEFAULT '17:00:00',
    slot_minutes INTEGER NOT NULL DEFAULT 30 CHECK (slot_minutes > 0 AND slot_minutes <= 240),
    schedule_weekdays VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5'
);

-- Create Patients table
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    contact_info VARCHAR(255) UNIQUE -- Prevent duplicate registrations
);

-- Create Appointments table
CREATE TABLE IF NOT EXISTS appointments (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER REFERENCES patients(id),
    doctor_id INTEGER REFERENCES doctors(id),
    appointment_date TIMESTAMP NOT NULL,
    status VARCHAR(50) DEFAULT 'booked' CHECK (status IN ('booked', 'rescheduled', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed Doctors (idempotent)
INSERT INTO doctors (name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays)
SELECT 'Dr. Alice Walker', 'Cardiologist', '09:00'::time, '17:00'::time, 30, '1,2,3,4,5'
WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE name = 'Dr. Alice Walker');

INSERT INTO doctors (name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays)
SELECT 'Dr. Bob Ross', 'Dermatologist', '10:00'::time, '16:00'::time, 45, '1,2,3,4,5'
WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE name = 'Dr. Bob Ross');

INSERT INTO doctors (name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays)
SELECT 'Dr. Charlie Brown', 'Pediatrician', '08:00'::time, '12:00'::time, 30, '1,2,3'
WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE name = 'Dr. Charlie Brown');
