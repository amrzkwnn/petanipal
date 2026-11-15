# Farm Memory — Supabase Setup & Integration Guide (Team Handoff)

This guide explains how to run and connect **Supabase Auth + Postgres** with the Farm Memory FastAPI backend and Stitch JS frontend on the main device.

---

## 1. What Is Already Prepared

- **`supabase/schema.sql`** — Postgres tables (`profiles`, `farms`, `crop_history`, `field_observations`, `rotation_comparisons`) with Row Level Security (RLS) enabled (`auth.uid() = user_id`).
- **`services/supabase_memory_store.py`** — Reads/writes `FarmMemory` directly to Supabase using the farmer's JWT so RLS is enforced on every query.
- **`main.py`** — Automatically switches to Supabase when `SUPABASE_URL` and `SUPABASE_KEY` are set in `.env` (falls back to local JSON in `data/farm_memories/` if unset).

---

## 2. Setup on the Main Device

### Step 1: Verify Database Schema & Auth in Supabase
1. In **Supabase Dashboard → SQL Editor**, confirm `supabase/schema.sql` has been executed (safe to re-run; uses `create table if not exists`).
2. In **Authentication → Providers**, enable **Email** (or **Phone OTP** if testing SMS login).
3. In **Project Settings → API**, copy:
   - **Project URL** (`SUPABASE_URL`)
   - **anon / public key** (`SUPABASE_KEY`)

### Step 2: Configure `.env` & Install Packages
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` (never commit `.env` to git):
```env
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here
OPENAI_REALTIME_MODEL=gpt-realtime-2.1-mini
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:5500
```

### Step 3: Run & Verify Backend
```powershell
fastapi dev main.py
```
Check `http://127.0.0.1:8000/health` — it should return:
```json
{
  "status": "ok",
  "locality": "Sungai Petani, Kedah",
  "storage": "supabase"
}
```

---

## 3. Connecting the Stitch JS Frontend

1. Sign the farmer in on the frontend using `@supabase/supabase-js` with `SUPABASE_URL` and `SUPABASE_KEY` (anon key).
2. Send the user's JWT (`session.access_token`) on every protected backend request:

   **REST endpoints** (header):
   ```js
   const res = await fetch("http://127.0.0.1:8000/api/farms/default", {
     headers: {
       Authorization: `Bearer ${session.access_token}`,
     },
   });
   ```
   - Pass `"default"` as `farm_id` if the farmer doesn't have a farm UUID yet — the backend will auto-create their `profiles` + `farms` row and return the real `farm_id` UUID.
   - Protected routes: `GET /api/farms/{farm_id}`, `GET /api/farms/{farm_id}/check-in`, `DELETE /api/farms/{farm_id}`, `POST /api/voice/turn`, `POST /api/voice/chat`, `POST /api/voice/confirm`.
   - Public routes (no token needed): `GET /health`, `GET /api/crops`, `GET /api/crops/{crop_id}`, `GET /api/questions`.

   **Realtime Voice WebSocket (`gpt-realtime-2.1-mini`)** (query param):
   ```js
   const ws = new WebSocket(
     `ws://127.0.0.1:8000/ws/voice/default/sess_001?language=ms&token=${encodeURIComponent(session.access_token)}`
   );
   ```

---

## 4. Integrating NASA POWER, GeoTanih & Rotation Engine

- **Read Farm Memory:** Use `memory_store.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)` to get the farmer-confirmed `FarmMemory` object (soil, water, crop history, and spontaneous field observations).
- **Save Rotation Comparisons:** Once the rotation engine compares 3 options, insert the result into `public.rotation_comparisons` (`farm_id`, `user_id`, `options`, `answer_basis`, `missing_info`) so the voice assistant can explain follow-up questions later.
- **NASA POWER & GeoTanih Caching:** Do not store raw weather/soil datasets in farmer tables, but cache GeoTanih/NASA POWER responses in backend memory or disk so they aren't re-fetched on every voice turn.

---

## 5. Privacy & Security Checklist

- **No raw audio storage:** Never save voice recordings, audio URLs, waveforms, or voiceprints in Supabase Postgres or Supabase Storage.
- **Confirmation before saving:** Keep `PendingConfirmation` ephemeral in memory; only write to Supabase after `POST /api/voice/confirm` with `accepted: true`.
- **Key safety:** Never put `OPENAI_API_KEY` or `SUPABASE_SERVICE_ROLE_KEY` in frontend JS or source control.
