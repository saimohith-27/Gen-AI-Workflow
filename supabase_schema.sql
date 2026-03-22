-- Supabase schema for owner/worker workflow control
-- Run this whole file in Supabase SQL editor.

-- Needed for gen_random_uuid()
create extension if not exists pgcrypto;

-- ----------------------------
-- Enums
-- ----------------------------
do $$
begin
  if not exists (select 1 from pg_type where typname = 'user_role') then
    create type public.user_role as enum ('owner', 'worker');
  end if;

  if not exists (select 1 from pg_type where typname = 'designation_type') then
    create type public.designation_type as enum ('hr', 'manager', 'lead', 'sales', 'legal', 'pwd', 'finance', 'it');
  end if;

  if not exists (select 1 from pg_type where typname = 'case_priority') then
    create type public.case_priority as enum ('low', 'normal', 'high');
  end if;

  if not exists (select 1 from pg_type where typname = 'case_status') then
    create type public.case_status as enum ('pending', 'in_progress', 'escalated', 'resolved', 'closed');
  end if;

  if not exists (select 1 from pg_type where typname = 'indent_category') then
    create type public.indent_category as enum ('it_asset', 'workspace', 'facility', 'cleaning', 'other');
  end if;

  if not exists (select 1 from pg_type where typname = 'indent_status') then
    create type public.indent_status as enum ('pending_review', 'under_review', 'approved', 'disapproved', 'escalated');
  end if;
end
$$;

-- ----------------------------
-- Helpers
-- ----------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.is_owner(uid uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.profiles p
    where p.id = uid and p.role = 'owner'
  );
$$;

-- ----------------------------
-- 1) profiles
-- Linked 1:1 with auth.users
-- ----------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  display_name text not null,
  role public.user_role not null default 'worker',
  designation public.designation_type,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger trg_profiles_updated_at
before update on public.profiles
for each row
execute function public.set_updated_at();

-- ----------------------------
-- 2) workflow_cases
-- Main complaint/workflow records
-- ----------------------------
create table if not exists public.workflow_cases (
  id uuid primary key default gen_random_uuid(),
  created_by uuid not null references public.profiles(id),
  assigned_to uuid references public.profiles(id),

  name text,
  email text,
  location text,
  complaint text not null,

  analysis jsonb not null default '{}'::jsonb,
  priority public.case_priority not null default 'normal',
  sla text not null default '48 hours',
  officer text,
  status public.case_status not null default 'pending',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_workflow_cases_created_by on public.workflow_cases(created_by);
create index if not exists idx_workflow_cases_assigned_to on public.workflow_cases(assigned_to);
create index if not exists idx_workflow_cases_status on public.workflow_cases(status);
create index if not exists idx_workflow_cases_priority on public.workflow_cases(priority);

create trigger trg_workflow_cases_updated_at
before update on public.workflow_cases
for each row
execute function public.set_updated_at();

-- ----------------------------
-- 3) case_audit_logs
-- Audit trail entries per case
-- ----------------------------
create table if not exists public.case_audit_logs (
  id bigserial primary key,
  case_id uuid not null references public.workflow_cases(id) on delete cascade,
  actor_user_id uuid references public.profiles(id),
  event_type text not null default 'info',
  message text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_case_audit_logs_case_id on public.case_audit_logs(case_id);
create index if not exists idx_case_audit_logs_created_at on public.case_audit_logs(created_at desc);

-- ----------------------------
-- 4) indent_requests
-- Indent approval workflow
-- ----------------------------
create table if not exists public.indent_requests (
  id uuid primary key default gen_random_uuid(),
  created_by uuid not null references public.profiles(id),
  assigned_to uuid references public.profiles(id),
  reviewed_by uuid references public.profiles(id),

  title text not null,
  indent_text text not null,
  category public.indent_category not null default 'other',
  route_to_designation public.designation_type not null default 'manager',

  estimated_cost numeric(12,2) not null default 0,
  budget_limit numeric(12,2),
  cost_difference numeric(12,2),

  status public.indent_status not null default 'pending_review',
  ai_analysis jsonb not null default '{}'::jsonb,

  review_reason text,
  approved_cost numeric(12,2),
  reviewed_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_indent_requests_created_by on public.indent_requests(created_by);
create index if not exists idx_indent_requests_assigned_to on public.indent_requests(assigned_to);
create index if not exists idx_indent_requests_status on public.indent_requests(status);
create index if not exists idx_indent_requests_route on public.indent_requests(route_to_designation);

create trigger trg_indent_requests_updated_at
before update on public.indent_requests
for each row
execute function public.set_updated_at();

-- ----------------------------
-- 5) indent_audit_logs
-- Audit trail for indent decisions
-- ----------------------------
create table if not exists public.indent_audit_logs (
  id bigserial primary key,
  indent_id uuid not null references public.indent_requests(id) on delete cascade,
  actor_user_id uuid references public.profiles(id),
  event_type text not null default 'info',
  message text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_indent_audit_logs_indent_id on public.indent_audit_logs(indent_id);
create index if not exists idx_indent_audit_logs_created_at on public.indent_audit_logs(created_at desc);

-- ----------------------------
-- RLS
-- ----------------------------
alter table public.profiles enable row level security;
alter table public.workflow_cases enable row level security;
alter table public.case_audit_logs enable row level security;
alter table public.indent_requests enable row level security;
alter table public.indent_audit_logs enable row level security;

-- profiles policies
create policy if not exists profiles_select_own
on public.profiles
for select
using (id = auth.uid());

create policy if not exists profiles_select_owner_all
on public.profiles
for select
using (public.is_owner(auth.uid()));

create policy if not exists profiles_update_own
on public.profiles
for update
using (id = auth.uid())
with check (id = auth.uid());

-- workflow_cases policies
create policy if not exists cases_select_owner_all
on public.workflow_cases
for select
using (public.is_owner(auth.uid()));

create policy if not exists cases_select_worker_scoped
on public.workflow_cases
for select
using (
  created_by = auth.uid() or assigned_to = auth.uid()
);

create policy if not exists cases_insert_worker
on public.workflow_cases
for insert
with check (
  created_by = auth.uid()
);

create policy if not exists cases_update_owner_all
on public.workflow_cases
for update
using (public.is_owner(auth.uid()))
with check (public.is_owner(auth.uid()));

create policy if not exists cases_update_worker_scoped
on public.workflow_cases
for update
using (created_by = auth.uid() or assigned_to = auth.uid())
with check (created_by = auth.uid() or assigned_to = auth.uid());

-- case_audit_logs policies
create policy if not exists logs_select_owner_all
on public.case_audit_logs
for select
using (public.is_owner(auth.uid()));

create policy if not exists logs_select_worker_scoped
on public.case_audit_logs
for select
using (
  exists (
    select 1
    from public.workflow_cases c
    where c.id = case_audit_logs.case_id
      and (c.created_by = auth.uid() or c.assigned_to = auth.uid())
  )
);

create policy if not exists logs_insert_worker_scoped
on public.case_audit_logs
for insert
with check (
  exists (
    select 1
    from public.workflow_cases c
    where c.id = case_audit_logs.case_id
      and (
        public.is_owner(auth.uid())
        or c.created_by = auth.uid()
        or c.assigned_to = auth.uid()
      )
  )
);

-- indent_requests policies
create policy if not exists indent_select_owner_all
on public.indent_requests
for select
using (public.is_owner(auth.uid()));

create policy if not exists indent_select_worker_scoped
on public.indent_requests
for select
using (
  created_by = auth.uid() or assigned_to = auth.uid() or reviewed_by = auth.uid()
);

create policy if not exists indent_insert_worker
on public.indent_requests
for insert
with check (created_by = auth.uid());

create policy if not exists indent_update_owner_all
on public.indent_requests
for update
using (public.is_owner(auth.uid()))
with check (public.is_owner(auth.uid()));

create policy if not exists indent_update_worker_scoped
on public.indent_requests
for update
using (created_by = auth.uid() or assigned_to = auth.uid())
with check (created_by = auth.uid() or assigned_to = auth.uid());

-- indent_audit_logs policies
create policy if not exists indent_logs_select_owner_all
on public.indent_audit_logs
for select
using (public.is_owner(auth.uid()));

create policy if not exists indent_logs_select_worker_scoped
on public.indent_audit_logs
for select
using (
  exists (
    select 1
    from public.indent_requests i
    where i.id = indent_audit_logs.indent_id
      and (i.created_by = auth.uid() or i.assigned_to = auth.uid() or i.reviewed_by = auth.uid())
  )
);

create policy if not exists indent_logs_insert_worker_scoped
on public.indent_audit_logs
for insert
with check (
  exists (
    select 1
    from public.indent_requests i
    where i.id = indent_audit_logs.indent_id
      and (
        public.is_owner(auth.uid())
        or i.created_by = auth.uid()
        or i.assigned_to = auth.uid()
      )
  )
);

-- Optional seed note:
-- Create users in Supabase Auth first, then insert matching rows into public.profiles.
-- Example:
-- insert into public.profiles (id, email, display_name, role, designation)
-- values ('<auth_user_uuid>', 'owner@demo.com', 'Platform Owner', 'owner', 'it');
