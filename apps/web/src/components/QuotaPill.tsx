import { Link } from "react-router-dom";
import { useMe } from "../lib/me";
import { quotaText } from "../lib/format";
import { ClockIcon } from "./icons";

export function QuotaPill() {
  const { me, loading } = useMe();
  if (loading) return <span className="quota-pill quota-loading" aria-hidden="true" />;
  if (!me) return null;
  const quota = me.quota;
  const exhausted = quota.remaining_today <= 0;
  return (
    <Link
      to="/account"
      className={`quota-pill ${exhausted ? "quota-empty" : ""}`}
      title={quotaText(quota)}
    >
      <ClockIcon size={15} />
      <span>{quotaText(quota)}</span>
    </Link>
  );
}
