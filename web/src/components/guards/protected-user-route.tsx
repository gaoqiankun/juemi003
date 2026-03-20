import { Navigate, Outlet, useLocation } from "react-router-dom";

import { hasUserApiKey } from "@/lib/user-config";

export function ProtectedUserRoute() {
  const location = useLocation();

  if (!hasUserApiKey()) {
    return <Navigate to="/setup" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  return <Outlet />;
}
