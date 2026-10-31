-- Sólo para desarrollo local: Supabase ya trae el esquema auth.
create schema if not exists auth;
create or replace function auth.uid() returns uuid language sql as 'select null::uuid';
