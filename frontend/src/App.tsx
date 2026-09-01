import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Spinner } from "@/components/primitives";
import { useAuth } from "@/store/auth";
import { applyTheme, useTheme } from "@/store/ui";
import Login from "@/pages/Login";
import Overview from "@/pages/Overview";

/**
 * Route-level code splitting. MapLibre (~200 kB) and ECharts are the two heavy
 * dependencies, and neither belongs in the first paint: the overview page is
 * the landing route and needs charts but no map, so the map chunk only loads
 * when someone opens the map or an asset. Overview is imported eagerly because
 * it *is* the landing route.
 */
const MapPage = lazy(() => import("@/pages/MapPage"));
const AssetsPage = lazy(() => import("@/pages/AssetsPage"));
const AddAssetPage = lazy(() => import("@/pages/AddAssetPage"));
const AssetDetailPage = lazy(() => import("@/pages/AssetDetailPage"));
const AlertsPage = lazy(() => import("@/pages/AlertsPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const ScanPage = lazy(() => import("@/pages/ScanPage"));

export default function App() {
  const theme = useTheme((s) => s.theme);
  const token = useAuth((s) => s.token);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  if (!token) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Overview />} />
        <Route
          path="/map"
          element={
            <Suspense fallback={<Spinner label="Loading map" />}>
              <MapPage />
            </Suspense>
          }
        />
        <Route
          path="/assets"
          element={
            <Suspense fallback={<Spinner label="Loading assets" />}>
              <AssetsPage />
            </Suspense>
          }
        />
        <Route
          path="/assets/new"
          element={
            <Suspense fallback={<Spinner label="Loading" />}>
              <AddAssetPage />
            </Suspense>
          }
        />
        <Route
          path="/assets/:id"
          element={
            <Suspense fallback={<Spinner label="Loading asset" />}>
              <AssetDetailPage />
            </Suspense>
          }
        />
        <Route
          path="/alerts"
          element={
            <Suspense fallback={<Spinner label="Loading alerts" />}>
              <AlertsPage />
            </Suspense>
          }
        />
        <Route
          path="/analytics"
          element={
            <Suspense fallback={<Spinner label="Loading analytics" />}>
              <AnalyticsPage />
            </Suspense>
          }
        />
        <Route
          path="/scan"
          element={
            <Suspense fallback={<Spinner label="Loading" />}>
              <ScanPage />
            </Suspense>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
