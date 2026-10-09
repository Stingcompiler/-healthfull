/**
 * Template for an API adapter. Files in this folder are loaded by e2e/helpers/api.ts on the
 * first factory call, except files whose name starts with "_" (like this one).
 *
 * When your module ships an endpoint that does what a factory does, copy this file to
 * `<module>.ts` (e.g. `patients.ts`), list the operation ids it calls and map the endpoint's
 * response to the factory's result shape. From then on the factory goes through your endpoint
 * whenever every listed operation is in frontend/openapi.json (`make api`), in every spec of
 * every module, and `E2E_FACTORY_MODE=api make e2e` proves it end to end. Until then it keeps
 * using the `e2e_fixture` command, so removing the adapter is always safe.
 *
 * The operation ids and fields below are an example only: use the ones your router defines.
 */
import { registerAdapter, type PatientRef } from "../api";

registerAdapter("createPatient", {
  operations: ["patients_create_patient"],
  async run(options, api) {
    // Options this endpoint does not cover go back to the fixture command (decide before any call).
    if (options.payer !== undefined || options.emergency || options.allergies?.length) return undefined;
    const reception = await api(options.as ?? "reception");
    const patient = await reception.call<PatientRef>("patients_create_patient", {
      body: {
        full_name_ar: options.full_name_ar ?? "مريض تجريبي",
        full_name_en: options.full_name_en ?? "Test Patient",
        sex: options.sex ?? "female",
        phone: options.phone ?? `09${String(Date.now()).slice(-8)}`,
        confirm_not_duplicate: options.confirm_not_duplicate ?? true,
      },
    });
    return { patient, coverage: null, allergies: [] };
  },
});
