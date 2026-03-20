import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useGen3d } from "@/app/gen3d-provider";
import { hasUserApiKey } from "@/lib/user-config";

export function ProtectedUserRoute() {
  const location = useLocation();
  const { config } = useGen3d();

  if (!config.token.trim() && !hasUserApiKey()) {
    return <Navigate to="/setup" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  return <Outlet />;
}
