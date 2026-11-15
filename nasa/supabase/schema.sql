-- Farm Memory — Supabase Postgres Schema + Row Level Security (RLS)
-- Paste into Supabase Dashboard -> SQL Editor and run once.

-- 1. Farmer profiles (links to Supabase Auth)
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  preferred_language text not null default 'ms' check (preferred_language in ('en', 'ms')),
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "Users can view own profile"
on public.profiles for select
to authenticated
using ((select auth.uid()) = id);

create policy "Users can insert own profile"
on public.profiles for insert
to authenticated
with check ((select auth.uid()) = id);

create policy "Users can update own profile"
on public.profiles for update
to authenticated
using ((select auth.uid()) = id);


-- 2. Farms (core Farm Memory record)
create table if not exists public.farms (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  farm_name text not null default 'My Farm',
  locality text not null default 'Sungai Petani, Kedah',
  latitude double precision,
  longitude double precision,

  -- TrackedValue JSONB objects: { value, evidence_label, confirmed_at, source }
  irrigation_availability jsonb not null default '{"value": "unknown", "evidence_label": "unknown"}'::jsonb,
  labour_availability jsonb not null default '{"value": "unknown", "evidence_label": "unknown"}'::jsonb,
  soil jsonb not null default '{
    "texture_feel": {"value": "unknown", "evidence_label": "unknown"},
    "waterlogging_duration": {"value": "unknown", "evidence_label": "unknown"},
    "flooded_last_season": {"value": "unknown", "evidence_label": "unknown"},
    "ph": {"value": null, "evidence_label": "unknown"},
    "soil_test_status": {"value": "unknown", "evidence_label": "unknown"},
    "trouble_spot": {"value": "unknown", "evidence_label": "unknown"}
  }'::jsonb,
  priorities jsonb not null default '{"water": 0, "soil_health": 0, "income": 0, "risk_reduction": 0}'::jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists farms_user_id_idx on public.farms using btree (user_id);

alter table public.farms enable row level security;

create policy "Farmers can manage their own farms"
on public.farms for all
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);


-- 3. Crop history (confirmed past seasons)
create table if not exists public.crop_history (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references public.farms(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  season text not null,
  crop_id text,
  raw_crop_name text not null,
  issue text,
  evidence_label text not null default 'verified_by_farmer',
  confirmed_at timestamptz not null default now()
);

create index if not exists crop_history_farm_id_idx on public.crop_history using btree (farm_id);
create index if not exists crop_history_user_id_idx on public.crop_history using btree (user_id);

alter table public.crop_history enable row level security;

create policy "Farmers can manage their own crop history"
on public.crop_history for all
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);


-- 4. Field observations (Ongoing Farm Memory: spontaneous events & check-ins)
-- Privacy rule: NEVER store raw audio, audio URLs, waveforms, or voiceprints here.
create table if not exists public.field_observations (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references public.farms(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  zone text not null default 'general',
  event_type text not null default 'general',
  affected_crop text,
  timing_or_duration text,
  observation text not null,
  evidence_label text not null default 'verified_by_farmer',
  source text not null default 'farmer-confirmed',
  recorded_at timestamptz not null default now()
);

create index if not exists field_observations_farm_id_idx on public.field_observations using btree (farm_id);
create index if not exists field_observations_user_id_idx on public.field_observations using btree (user_id);

alter table public.field_observations enable row level security;

create policy "Farmers can manage their own field observations"
on public.field_observations for all
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);


-- 5. Rotation comparisons (optional audit & follow-up Q&A history for teammate's engine)
create table if not exists public.rotation_comparisons (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references public.farms(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  options jsonb not null,
  answer_basis jsonb not null default '[]'::jsonb,
  missing_info jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists rotation_comparisons_farm_id_idx on public.rotation_comparisons using btree (farm_id);
create index if not exists rotation_comparisons_user_id_idx on public.rotation_comparisons using btree (user_id);

alter table public.rotation_comparisons enable row level security;

create policy "Farmers can manage their own rotation comparisons"
on public.rotation_comparisons for all
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);
