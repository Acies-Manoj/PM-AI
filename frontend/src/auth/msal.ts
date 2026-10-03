import { InteractionRequiredAuthError, PublicClientApplication } from "@azure/msal-browser";

// The SPA's own app registration ("pmai-web").
const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined;
const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID as string | undefined;
// The API's app registration ("pmai-api"): the token's audience. Only needed if VITE_API_SCOPE is not set.
const apiClientId = import.meta.env.VITE_ENTRA_API_CLIENT_ID as string | undefined;

/** Auth is on only when both Entra ids are configured. */
export const authEnabled = Boolean(clientId && tenantId);

export const msalInstance: PublicClientApplication | null = authEnabled
  ? new PublicClientApplication({
      auth: {
        clientId: clientId!,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        redirectUri: window.location.origin,
      },
      cache: { cacheLocation: "sessionStorage" },
    })
  : null;

/**
 * The scope the API token is requested for. It must name the *API* app (pmai-api), not this
 * SPA, or the token's audience will not match what the backend accepts. Set VITE_API_SCOPE
 * (e.g. api://<api client id>/access_as_user) or VITE_ENTRA_API_CLIENT_ID.
 */
export const apiScopes: string[] = [
  (import.meta.env.VITE_API_SCOPE as string | undefined) ??
    `api://${apiClientId ?? clientId}/access_as_user`,
];

if (authEnabled && !import.meta.env.VITE_API_SCOPE && !apiClientId) {
  console.warn(
    "Entra auth is on but neither VITE_API_SCOPE nor VITE_ENTRA_API_CLIENT_ID is set; " +
      "requesting a token for the SPA's own client id, which the backend will reject if the API is a separate app registration.",
  );
}

// Once one request has started the sign-in redirect, every other request waits for the page to
// navigate away instead of firing unauthenticated (a guaranteed 401) or starting a second redirect.
let redirectStarted = false;

function waitForRedirect(): Promise<never> {
  return new Promise<never>(() => {
    /* the browser is leaving the page */
  });
}

/** Returns a bearer token, or null when auth is disabled. */
export async function getAccessToken(forceRefresh = false): Promise<string | null> {
  if (!authEnabled || !msalInstance) return null;
  await msalInstance.initialize();
  if (redirectStarted) return waitForRedirect();

  const account = msalInstance.getActiveAccount() ?? msalInstance.getAllAccounts()[0];
  if (!account) {
    redirectStarted = true;
    void msalInstance.loginRedirect({ scopes: apiScopes });
    return waitForRedirect();
  }
  try {
    const result = await msalInstance.acquireTokenSilent({ scopes: apiScopes, account, forceRefresh });
    return result.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      if (!redirectStarted) {
        redirectStarted = true;
        void msalInstance.acquireTokenRedirect({ scopes: apiScopes, account });
      }
      return waitForRedirect();
    }
    throw err;
  }
}
