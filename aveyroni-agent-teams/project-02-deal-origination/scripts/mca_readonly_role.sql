-- Optional: a scoped, read-only Postgres role for project-02 to query the
-- MCA registry, instead of handing it Syndiq's SUPABASE_SERVICE_ROLE_KEY
-- (which can write, and can read every other table in that project).
--
-- Run this once in the Syndiq Supabase project's SQL Editor, then create an
-- API key for this role however your Supabase plan supports custom roles
-- (Dashboard -> Database -> Roles, or a JWT signed with this role name).
-- If your plan does not support custom Postgres roles for PostgREST, the
-- pragmatic fallback is the service_role key with this note kept as a TODO.

CREATE ROLE aveyroni_mca_reader NOLOGIN;

GRANT USAGE ON SCHEMA public TO aveyroni_mca_reader;
GRANT SELECT ON public.mca_companies TO aveyroni_mca_reader;
GRANT SELECT ON public.mca_company_enrichment TO aveyroni_mca_reader;
GRANT SELECT ON public.mca_companies_enriched TO aveyroni_mca_reader;

-- Nothing else: no INSERT/UPDATE/DELETE, no buyers/deals/thesis tables, no
-- RPC EXECUTE grants. project-02 only ever runs SELECT against
-- mca_companies_enriched (see orchestrator/mca_registry.py).

COMMENT ON ROLE aveyroni_mca_reader IS
  'Read-only cross-project role for the Aveyroni/Hermes deal-origination '
  'desk (project-02-deal-origination) to pre-filter India company discovery '
  'from the MCA registry. Grants SELECT only, on the three mca_* objects.';
