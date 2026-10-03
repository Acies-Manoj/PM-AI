import { useEffect, useState, type ReactNode } from "react";
import { MsalProvider } from "@azure/msal-react";
import { apiScopes, authEnabled, msalInstance } from "./msal";

// React StrictMode runs effects twice in development; only start one sign-in redirect.
let loginStarted = false;

function Gate({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const msal = msalInstance!;
    let cancelled = false;
    (async () => {
      try {
        await msal.initialize();
        const result = await msal.handleRedirectPromise();
        if (result?.account) msal.setActiveAccount(result.account);
        const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (account) {
          msal.setActiveAccount(account);
          if (!cancelled) setSignedIn(true);
        } else {
          if (!loginStarted) {
            loginStarted = true;
            await msal.loginRedirect({ scopes: apiScopes });
          }
          return;
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Sign-in failed.");
      }
      if (!cancelled) setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (signedIn) return <>{children}</>;
  if (!ready && !error) return <p style={{ padding: 24 }}>Signing in...</p>;
  return (
    <div style={{ padding: 24 }}>
      {error && <p>{error}</p>}
      <button type="button" onClick={() => void msalInstance!.loginRedirect({ scopes: apiScopes })}>
        Sign in with Microsoft
      </button>
    </div>
  );
}

export default function AuthGate({ children }: { children: ReactNode }) {
  if (!authEnabled || !msalInstance) return <>{children}</>;
  return (
    <MsalProvider instance={msalInstance}>
      <Gate>{children}</Gate>
    </MsalProvider>
  );
}
