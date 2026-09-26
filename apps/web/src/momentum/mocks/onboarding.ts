import { http, HttpResponse } from 'msw';

type OnboardingStatus = {
  created_project: boolean;
  tried_import: boolean;
  used_command_palette: boolean;
  dismissed: boolean;
};

const DEFAULT_STATUS: OnboardingStatus = {
  created_project: false,
  tried_import: false,
  used_command_palette: false,
  dismissed: false,
};

/** In-memory S2.7.3 onboarding-checklist API (`GET/PATCH /me/onboarding`). */
export function onboardingHandlers(base = '', initial: Partial<OnboardingStatus> = {}) {
  let status: OnboardingStatus = { ...DEFAULT_STATUS, ...initial };
  return [
    http.get(`*${base}/api/v1/me/onboarding`, () => HttpResponse.json(status)),
    http.patch(`*${base}/api/v1/me/onboarding`, async ({ request }) => {
      const patch = (await request.json()) as Partial<OnboardingStatus>;
      status = { ...status, ...patch };
      return HttpResponse.json(status);
    }),
  ];
}
