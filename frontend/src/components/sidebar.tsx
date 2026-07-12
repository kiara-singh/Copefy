import { NavLink } from "react-router-dom";

const nav_items = [
  { to: "/", label: "Chat", end: true },
  { to: "/journal", label: "Journal Entries", end: false },
];

function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="px-6 py-5">
        <span className="text-xl font-bold tracking-tight text-indigo-600">
          Copefy
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3">
        {nav_items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}

export default Sidebar;
