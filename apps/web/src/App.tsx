import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AccountPage } from "./pages/AccountPage";
import { JobPage } from "./pages/JobPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { StudioPage } from "./pages/StudioPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<StudioPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="jobs/:id" element={<JobPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}