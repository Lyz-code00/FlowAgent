import {
  BookOpen,
  Bot,
  ChevronRight,
  Gauge,
  LogOut,
  MessagesSquare,
  ClipboardList,
  MessageCircleWarning,
  Settings,
  ShieldCheck,
  UserRoundCog
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

const nav = [
  { to: "/", label: "运营概览", icon: Gauge },
  { to: "/conversations", label: "会话与 Trace", icon: MessagesSquare },
  { to: "/knowledge", label: "知识库", icon: BookOpen },
  { to: "/users", label: "用户与权限", icon: UserRoundCog },
  { to: "/summaries", label: "讨论沉淀", icon: ClipboardList },
  { to: "/feedback", label: "反馈与 Bad Case", icon: MessageCircleWarning },
  { to: "/configuration", label: "运行配置", icon: Settings }
];

const titles: Record<string, string> = {
  "/": "运营概览",
  "/conversations": "会话与 Trace",
  "/knowledge": "知识库",
  "/users": "用户与权限",
  "/summaries": "讨论沉淀",
  "/feedback": "反馈与 Bad Case",
  "/configuration": "运行配置"
};

export default function Shell({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
  const location = useLocation();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark"><Bot size={23} /></div>
          <div><strong>FlowAgent</strong><span>研发协同控制台</span></div>
        </div>
        <nav className="nav-list" aria-label="主导航">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}>
              <Icon size={19} />
              <span>{label}</span>
              <ChevronRight className="nav-list__arrow" size={15} />
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__security">
          <ShieldCheck size={17} />
          <div><strong>安全访问</strong><span>管理接口已鉴权</span></div>
        </div>
        <button className="sidebar__logout" onClick={onLogout}>
          <LogOut size={17} />退出控制台
        </button>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="topbar__crumb"><span>FlowAgent</span><ChevronRight size={14} />{titles[location.pathname] ?? "管理控制台"}</div>
          <div className="topbar__status"><i />服务运行中</div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
