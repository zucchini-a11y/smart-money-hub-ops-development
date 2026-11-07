import { useState } from "react";
import { Activity, ArrowUpRight, CheckCircle2, CircleAlert, FileText, MessageSquareText, Search } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import "./_group.css";

type CaseRow = {
  id: string;
  question: string;
  status: "open" | "replied" | "closed";
  created: string;
  updated: string;
};

const cases: CaseRow[] = [
  { id: "CASE-4812", question: "I can’t find the lesson from my member dashboard.", status: "open", created: "Today · 9:18 AM", updated: "5 min ago" },
  { id: "CASE-4811", question: "Could someone explain why the signal changed?", status: "open", created: "Today · 8:54 AM", updated: "18 min ago" },
  { id: "CASE-4808", question: "Where can I find the breakdown behind the weekly recap?", status: "replied", created: "Yesterday · 11:06 AM", updated: "Yesterday" },
  { id: "CASE-4799", question: "How do I update my reminder preferences?", status: "closed", created: "Mon · 3:02 PM", updated: "Mon" },
];

const metrics: Array<{ label: string; value: string; Icon: LucideIcon }> = [
  { label: "Open cases", value: "12", Icon: MessageSquareText },
  { label: "Delivery uncertain", value: "1", Icon: CircleAlert },
  { label: "Replied", value: "36", Icon: CheckCircle2 },
  { label: "Closed", value: "104", Icon: FileText },
];

export function Current() {
  const [selected, setSelected] = useState<CaseRow>(cases[0]!);
  const [notice, setNotice] = useState("");
  return <div className="smh-support-extract">
    <main style={{maxWidth:1440,margin:"0 auto",padding:"34px clamp(18px,4vw,54px) 56px"}}>
      <header style={{display:"flex",alignItems:"end",justifyContent:"space-between",gap:18,flexWrap:"wrap",marginBottom:26}}>
        <div><div className="label">VAYDA OPERATIONS</div><h1 style={{font:"700 clamp(28px,3vw,38px) Manrope,sans-serif",letterSpacing:"-.045em",color:"#233c34",margin:"8px 0 7px"}}>Support</h1><p style={{color:"#7a837d",fontSize:13,margin:0}}>Review member questions and send a helpful reply.</p></div>
        <div style={{display:"flex",alignItems:"center",gap:10,flexWrap:"wrap"}}>
          <button className="button" onClick={()=>setNotice("Website chats open in a separate support view in the current experience.")} data-testid="button-current-website-chats">Website Chats <ArrowUpRight size={14}/></button>
          <span style={{display:"inline-flex",alignItems:"center",gap:7,color:"#6b7c71",fontSize:11}}><Activity size={14}/> Updates automatically</span>
        </div>
      </header>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,minmax(0,1fr))",gap:12,marginBottom:23}} className="stats">
        {metrics.map(({label,value,Icon})=><article className="surface" key={label} style={{padding:"15px 17px",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div><div style={{fontSize:11,color:"#7a837d"}}>{label}</div><strong style={{display:"block",marginTop:7,font:"700 25px Manrope,sans-serif",color:"#2b4139"}}>{value}</strong></div><span style={{width:34,height:34,borderRadius:10,display:"grid",placeItems:"center",background:"#e8eee8",color:"#3d715e"}}><Icon size={16}/></span>
        </article>)}
      </div>
      {notice && <div role="status" style={{marginBottom:14,padding:12,background:"#f4ead4",borderRadius:8,color:"#795c28",fontSize:12}}>{notice}</div>}
      <section className="surface" style={{overflow:"hidden"}}>
        <div style={{padding:"18px 21px",borderBottom:"1px solid #ebe6dd",display:"flex",alignItems:"center",justifyContent:"space-between",gap:14,flexWrap:"wrap"}}>
          <div><div className="label">MEMBER CASES</div><p style={{margin:"5px 0 0",fontSize:11,color:"#879088"}}>4 sample records · website chats appear in a separate view</p></div>
          <div className="toolbar" style={{display:"flex",alignItems:"center",gap:9}}><label style={{position:"relative"}}><Search size={14} style={{position:"absolute",left:10,top:10,color:"#8a948d"}}/><input aria-label="Search current cases" placeholder="Search cases or members" style={{width:220,border:"1px solid #deded3",borderRadius:7,background:"#fffefa",padding:"9px 10px 9px 31px",fontSize:12}}/></label><select aria-label="Filter current cases" style={{border:"1px solid #deded3",borderRadius:7,padding:"9px 11px",fontSize:12,background:"#fffefa",color:"#59665d"}}><option>All statuses</option><option>Open</option><option>Replied</option><option>Closed</option></select></div>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"minmax(0,1.1fr) minmax(330px,.9fr)"}}>
          <div style={{overflowX:"auto"}}>
            <table style={{width:"100%",borderCollapse:"collapse",textAlign:"left"}}><thead><tr style={{background:"#f7f5ef",color:"#8a928c",font:"500 10px var(--app-font-mono)",letterSpacing:".08em",textTransform:"uppercase"}}><th style={{padding:"12px 16px"}}>Case</th><th style={{padding:"12px 16px"}}>Member question</th><th style={{padding:"12px 16px"}}>Status</th></tr></thead><tbody>{cases.map((item)=><tr key={item.id} className="row-hover" onClick={()=>setSelected(item)} style={{cursor:"pointer",borderTop:"1px solid #eee9e1",background:selected.id===item.id?"#f3f6f0":"transparent"}}>
              <td style={{padding:"14px 16px",whiteSpace:"nowrap"}}><strong style={{font:"500 11px var(--app-font-mono)",color:"#718279"}}>{item.id}</strong><div className="muted" style={{marginTop:5}}>Member · protected</div></td>
              <td style={{padding:"14px 16px",minWidth:220,maxWidth:360}}><span style={{display:"block",fontSize:12,lineHeight:1.45,color:"#3b4941"}}>{item.question}</span><span className="muted">{item.updated}</span></td>
              <td style={{padding:"14px 16px"}}><span className={`status status-${item.status}`}>{item.status}</span></td>
            </tr>)}</tbody></table>
          </div>
          <aside style={{padding:22,borderLeft:"1px solid #ebe6dd",background:"#fcfbf7"}}>
            <div className="label">CASE CONVERSATION</div><h2 style={{font:"700 18px Manrope,sans-serif",color:"#2d4239",margin:"10px 0 8px"}}>{selected.id}</h2><span className={`status status-${selected.status}`}>{selected.status}</span>
            <p style={{fontSize:13,lineHeight:1.6,color:"#46564d",margin:"18px 0"}}>{selected.question}</p>
            <div style={{borderTop:"1px solid #ebe6dd",paddingTop:15,color:"#879088",fontSize:11}}>Received {selected.created}<br/>Last updated {selected.updated}</div>
            <div style={{marginTop:20,padding:13,borderRadius:8,background:"#fffefa",border:"1px solid #e8e3d9",fontSize:11,color:"#718078"}}>In the current page, cases can be reviewed here, but website chats are managed on a separate page.</div>
          </aside>
        </div>
        <footer style={{padding:"10px 18px",borderTop:"1px solid #ebe6dd",color:"#8b948b",fontSize:10}}>Visual baseline · fictional sample data · not connected to a live support account</footer>
      </section>
    </main>
  </div>;
}
