"use strict";
const $ = selector => document.querySelector(selector);
let settings, status, models, libraryPage = 1, libraryQuery = "", libraryState = "", librarySource = "", fingerprint = "";
const communityNames={"8de5ffef-1c73-4c9b-a83f-b75c953201ba":"Fing (incluye InCo)","36bd9ee5-261b-4db6-8dd6-e96cafcb1fd4":"InCo"};
let rendering = false;
let libraryView="all",libraryDay="";
const names = {home: "Boletín diario", library: "Biblioteca", activity: "Actividad", settings: "Configuración", paper: "Ficha del paper"};
const labels = {queued:"En cola", running:"En curso", done:"Completado", error:"Error", partial:"Parcial", cancelled:"Cancelado", completed:"Completada", interrupted:"Interrumpida"};
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key in node && key !== "list") node[key] = value;
    else node.setAttribute(key, value);
  }
  append(node,...children);
  return node;
}
function append(node,...children){
  for(const child of children.flat(Infinity)) if(child!==null && child!==undefined && child!==false) node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
async function api(path, options = {}) {
  const response = await fetch(`/api/${path}`, { ...options, headers: {"Content-Type":"application/json", "X-Radar-Request":"1", ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
function toast(message, error = false) {
  const node = $("#toast"); node.textContent = message; node.className = error ? "error" : ""; node.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.hidden = true, 7000);
}
async function action(fn, success) {
  try { await fn(); if (success) toast(success); fingerprint = ""; await refresh(true); }
  catch (error) { toast(error.message, true); }
}
function button(text, fn, cls = "") { return el("button", {type:"button", class:cls, onclick:() => action(fn)}, text); }
function draftButton(text,fn){return el("button",{type:"button",onclick:async()=>{try{await fn();}catch(error){toast(error.message,true);}}},text);}
function cancelButton(job){
  if(!["queued","running"].includes(job.status)) return null;
  const node=button("Cancelar",async()=>{
    node.disabled=true;node.textContent="Cancelando…";
    try{await api(`jobs/${job.id}/cancel`,{method:"POST"});}
    finally{node.disabled=false;node.textContent="Cancelar";}
  },"danger");
  node.setAttribute("aria-label",`Cancelar ${jobName(job.kind)}: ${job.title || "este documento"}`);
  return node;
}
function jobName(kind){return {summary:"Resumen",brief:"Resumen anterior",overview:"Resumen anterior",analysis:"Informe anterior (archivado)"}[kind] || kind;}
function dayLabel(day){return new Intl.DateTimeFormat("es-UY",{dateStyle:"long",timeZone:"UTC"}).format(new Date(`${day}T12:00:00Z`));}
function date(value, time = false) {
  return value ? new Intl.DateTimeFormat("es-UY", {dateStyle:"medium", ...(time ? {timeStyle:"short"} : {}), timeZone:settings?.timezone || "America/Montevideo"}).format(new Date(value)) : "Todavía no";
}
function tag(text, cls = "") { return el("span", {class:`tag ${cls}`}, text); }
function safeLink(url, text, cls = "") {
  // Enlaces de fuente, no destinos inventados por el modelo.
  let valid = false;
   try { const parsed = new URL(url); valid = parsed.protocol === "https:" && ["arxiv.org", "www.arxiv.org", "www.colibri.udelar.edu.uy"].includes(parsed.hostname) && !parsed.username && !parsed.password && (!parsed.port || parsed.port === "443"); } catch (_) {}
  return valid ? el("a", {href:url, target:"_blank", rel:"noopener noreferrer", class:cls}, text) : el("span", {}, text);
}
function hero(title, subtitle, ...actions) {
  return el("div", {class:"hero"}, el("div", {}, title ? el("h1", {}, title) : null, el("p", {class:"subtitle"}, subtitle)), el("div", {class:"actions"}, actions));
}
function sourceName(source){return source==="colibri" ? "Colibrí" : "arXiv";}
function quota(source){
  const total=settings.bulletin_limit;
  const local=settings.colibri_bulletin_limit;
  return source==="colibri" ? (settings.colibri_enabled ? local : 0) : (settings.arxiv_enabled ? total-(settings.colibri_enabled ? local : 0) : 0);
}
function pdfButton(paper){
  if(paper.pdf_url)return safeLink(paper.pdf_url,"Ver PDF ↗","button");
  if(paper.source!=="colibri")return null;
  const node=el("button",{type:"button",onclick:async()=>{
    const tab=window.open("about:blank","_blank");if(tab)tab.opener=null;
    node.disabled=true;node.textContent="Buscando PDF…";
    try{
      const result=await api(`papers/${paper.id}/pdf`,{method:"POST"});
      const link=safeLink(result.url,"Ver PDF ↗","button");
      if(link.tagName!=="A")throw new Error("La fuente no devolvió un enlace PDF autorizado.");
      paper.pdf_url=result.url;
      if(tab)tab.location.href=result.url;else toast("El navegador bloqueó la pestaña. Pulsa de nuevo Ver PDF para abrirlo.");
      node.replaceWith(link);
    }catch(error){if(tab)tab.close();toast(error.message,true);}
    finally{node.disabled=false;node.textContent="Ver PDF ↗";}
  }},"Ver PDF ↗");return node;
}
function paperTags(paper){return paper.categories.map(c=>tag(communityNames[c] || (/^[a-f0-9-]{36}$/.test(c) ? `Comunidad ${c.slice(0,8)}` : c)));}
function interestControls(paper){
  return el("div",{class:"interest-actions"},
    button(paper.interest===1 ? "✓ Me interesa" : "Me interesa",()=>api(`papers/${paper.id}`,{method:"PATCH",body:JSON.stringify({interest:1})}),paper.interest===1 ? "selected-interest" : ""),
    button(paper.interest===-1 ? "✓ No me interesa" : "No me interesa",()=>api(`papers/${paper.id}`,{method:"PATCH",body:JSON.stringify({interest:-1})}),paper.interest===-1 ? "selected-interest" : ""),
    paper.interest ? button("Quitar marca",()=>api(`papers/${paper.id}`,{method:"PATCH",body:JSON.stringify({interest:0})})) : null);
}
function card(paper, bulletinDay="") {
  const brief = paper.brief;
  return el("article", {class:"paper-card"},
    el("div", {class:"paper-meta"}, tag(sourceName(paper.source),paper.source==="colibri"?"green":""), ...paperTags(paper),
      paper.source==="arxiv" ? tag(paper.is_revision ? `Nueva versión · v${paper.version}` : `v${paper.version}`) : tag(paper.document_type || "Documento"),
      paper.source==="colibri" ? `Depositado: ${date(paper.updated)}` : date(paper.updated), paper.overview ? tag(paper.overview.scope==="pdf_unavailable" ? "Resumen parcial" : "Resumen disponible", paper.overview.scope==="pdf_unavailable" ? "amber" : "green") : null),
    el("h2", {}, el("a", {href:`#paper/${paper.id}${bulletinDay ? `/${bulletinDay}` : ""}`}, paper.title)),
    el("p", {class:"summary",...(brief?.language && brief.language !== "other" ? {lang:brief.language} : {})}, brief ? brief.summary : paper.abstract ? paper.abstract.slice(0, 320) + (paper.abstract.length > 320 ? "…" : "") : "Sin abstract disponible en la fuente."),
    brief ? el("div", {class:"relevance"}, "Afinidad temática · ", brief.relevance_reason) : null,
    el("div", {class:"card-bottom"}, el("div", {class:"paper-meta"}, tag(brief ? "Resumen del abstract" : "Metadatos originales"), paper.is_read ? tag("Leído") : null, paper.favorite ? tag("Favorito", "green") : null,
      paper.interest ? tag(paper.interest===1 ? "Me interesó" : "No me interesó",paper.interest===1 ? "green" : "amber") : null),
      el("div", {class:"actions"}, safeLink(paper.url, "Original ↗", "button"), pdfButton(paper),el("a", {href:`#paper/${paper.id}${bulletinDay ? `/${bulletinDay}` : ""}`, class:"button primary"}, "Ver resumen →"))),interestControls(paper));
}
async function home() {
  const [bulletin, activity] = await Promise.all([api("bulletin"), api("activity")]);
  const node = el("div", {}, hero(null, `Hasta ${quota("colibri")} resúmenes de Colibrí y ${quota("arxiv")} de arXiv por día. Contenido en el idioma original.`,
    button(status.scanning ? "Buscando…" : "Buscar novedades", () => api("scan", {method:"POST"}), "primary"),
    button(settings.pause_summaries ? "Reanudar resúmenes" : "Pausar resúmenes", async () => {settings = await api("settings", {method:"PUT", body:JSON.stringify({...settings, pause_summaries:!settings.pause_summaries})});})));
  const ready = bulletin.papers.filter(p => p.overview).length;
  const pending = status.queue.filter(j => j.kind==="summary" && (j.status === "queued" || j.status === "running")).reduce((sum,j) => sum + j.count, 0);
  const metrics = [
    ["Última consulta", date(status.last_scan, true), "Consulta de metadatos, no finalización de análisis"],
    ["En este boletín", `${ready} / ${bulletin.papers.length} resúmenes`, `${pending} tareas pendientes · ${settings.model}`],
    ["Próxima cita", settings.schedule_enabled ? date(status.next_run, true) : "Automatización pausada", "Recupera la ejecución pendiente al encender el equipo"],
  ];
  node.append(el("div", {class:"metrics"}, metrics.map(([label,value,hint]) => el("div", {class:"metric"}, el("label",{},label),el("strong",{},value),el("small",{},hint)))));
  const latest = activity.runs[0];
   if (["error","partial"].includes(latest?.status)) node.append(el("div", {class:"notice warn"}, "La última búsqueda tuvo un problema: ", latest.error, " · La otra fuente puede seguir funcionando. Las pausas se respetan automáticamente."));
  node.append(el("div", {class:"section-title"}, el("h2", {}, "Tu último boletín"), el("span", {class:"muted"}, bulletin.run ? date(bulletin.run.started_at) : "Esperando la primera búsqueda")));
  if (bulletin.papers.length) {
    for(const source of ["colibri","arxiv"]){
      if(!settings[`${source}_enabled`]) continue;
      const papers=bulletin.papers.filter(p=>p.source===source);
      node.append(el("div",{class:"source-heading"},el("h2",{},sourceName(source)),el("span",{class:"muted"},`${papers.length} visibles · cupo diario ${quota(source)}`)),
        papers.length ? el("div",{class:"cards"},papers.map(p=>card(p,bulletin.day))) : el("p",{class:"muted"},"Sin novedades pendientes de revisar para esta fuente."));
    }
  }
   else node.append(el("div", {class:"empty"}, el("h2",{},"Todavía no hay un boletín"), el("p",{},"El servicio consultará arXiv y preparará los resúmenes con tu modelo local. Puedes iniciar una búsqueda ahora o revisar la configuración."), el("a",{href:"#settings",class:"button"},"Revisar configuración")));
  node.append(el("div", {class:"notice"}, `${bulletin.marked_count || 0} documentos con marca de interés. Ambas marcas quedan visibles en el boletín y la biblioteca; NO se envían al modelo ni modifican los filtros.`));
  node.append(el("div", {class:"notice"}, "Los cupos son máximos, no una promesa de novedades diarias. Si faltan trabajos de una fuente, no se rellena su cupo con la otra. Selección por filtros y actualidad, no ranking de calidad científica."));
  return {node, data:JSON.stringify([bulletin, status, settings, latest])};
}
async function library() {
  const archive=await api("bulletins");
  const routedDay=route().id;
  if(routedDay && /^\d{4}-\d{2}-\d{2}$/.test(routedDay)){libraryView="bulletins";if(libraryDay!==routedDay)libraryPage=1;libraryDay=routedDay;}
  if(libraryView==="bulletins" && !libraryDay)libraryDay=archive.days[0]?.day || "";
  const data = libraryView==="bulletins" && !libraryDay ? {papers:[],total:0,page:1} : await api(`papers?q=${encodeURIComponent(libraryQuery)}&state=${libraryState}&page=${libraryPage}${librarySource ? `&source=${librarySource}` : ""}${libraryView==="bulletins" && libraryDay ? `&bulletin_day=${libraryDay}` : ""}`);
  const input = el("input", {type:"search", placeholder:"Buscar por título o abstract…", value:libraryQuery, "aria-label":"Buscar artículos"});
  let timer;
  input.addEventListener("input", () => {clearTimeout(timer); timer = setTimeout(() => {libraryQuery = input.value; libraryPage = 1; render(true);}, 450);});
  const select = el("select", {"aria-label":"Filtrar artículos", onchange:event => {libraryState = event.target.value; libraryPage=1; render(true);}},
    [["","Todos"],["interested","Me interesó"],["not_interested","No me interesó"],["unrated","Sin marca de interés"],["unread","No leídos"],["favorites","Favoritos"],["summary","Con resumen"],["revisions","Nuevas versiones"]].map(([value,text]) => el("option", {value,selected:value===libraryState},text)));
  const sources=el("select",{"aria-label":"Filtrar fuente",onchange:event=>{librarySource=event.target.value;libraryPage=1;render(true);}},
    [["","Todas las fuentes"],["colibri","Colibrí"],["arxiv","arXiv"]].map(([value,text])=>el("option",{value,selected:value===librarySource},text)));
  const node = el("div", {}, hero("Biblioteca", `${data.total} documentos encontrados. Las marcas de interés son personales, no feedback del modelo.`), el("div", {class:"filters"},input,sources,select));
  const grouping=el("select",{"aria-label":"Ver biblioteca por boletín",onchange:event=>{
    libraryView=event.target.value;libraryPage=1;
    if(libraryView==="all"){libraryDay="";location.hash="#library";render(true);}else{libraryDay=archive.days[0]?.day || "";location.hash=libraryDay ? `#library/${libraryDay}` : "#library";render(true);}
  }},[["all","Todos los artículos"],["bulletins","Artículos por boletín"]].map(([value,label])=>el("option",{value,selected:libraryView===value},label)));
  const archiveControls=el("div",{class:"bulletin-navigation"},grouping);
  if(libraryView==="bulletins"){
    const days=el("select",{"aria-label":"Elegir día de boletín",onchange:event=>{libraryDay=event.target.value;libraryPage=1;location.hash=`#library/${libraryDay}`;}},archive.days.map(item=>el("option",{value:item.day,selected:item.day===libraryDay},`${dayLabel(item.day)} · ${item.total} artículos`)));
    days.disabled=!archive.days.length;
    const index=archive.days.findIndex(item=>item.day===libraryDay);
    const move=offset=>{libraryPage=1;libraryDay=archive.days[index+offset].day;location.hash=`#library/${libraryDay}`;};
    const older=button("← Boletín anterior",()=>move(1));older.disabled=index<0 || index>=archive.days.length-1;
    const newer=button("Boletín siguiente →",()=>move(-1));newer.disabled=index<=0;
    archiveControls.append(days,older,newer);
    const remove=button("Eliminar boletín completo",async()=>{
      const day=libraryDay;
      if(!window.confirm(`¿Eliminar el boletín completo del ${dayLabel(day)}? Incluye todos sus artículos, aunque haya filtros activos. Los documentos, resúmenes y marcas se conservan en la biblioteca.`))return;
      await api(`bulletins/${day}`,{method:"DELETE"});
      const remaining=archive.days.filter(item=>item.day!==day);
      libraryDay=remaining[Math.min(Math.max(index,0),remaining.length-1)]?.day || "";libraryPage=1;
      location.hash=libraryDay ? `#library/${libraryDay}` : "#library";
      toast("Boletín eliminado. Los documentos siguen en la biblioteca.");
    },"danger");remove.disabled=index<0;archiveControls.append(remove);
    node.append(el("p",{class:"coverage"},archive.days.length ? `Todos los días con boletines guardados (${archive.days.length}). Se muestran los artículos originales de cada día, incluidas sus marcas de interés, sin aplicar los cupos actuales.` : "Todavía no hay boletines guardados."));
  }
  node.insertBefore(archiveControls,node.children[1]);
  node.append(data.papers.length ? el("div", {class:"cards"},data.papers.map(p=>card(p,libraryView==="bulletins" ? libraryDay : ""))) : el("div",{class:"empty"},el("h2",{},"No hay artículos con estos filtros"),el("p",{},"Prueba otra búsqueda o espera a la siguiente consulta de arXiv.")));
  const prev = button("← Anterior", async () => {libraryPage--;}); prev.disabled = libraryPage <= 1;
  const next = button("Siguiente →", async () => {libraryPage++;}); next.disabled = libraryPage * 30 >= data.total;
  node.append(el("div", {class:"pagination"},prev,el("span",{},`Página ${libraryPage} de ${Math.max(1,Math.ceil(data.total/30))}`),next));
  return {node,data:JSON.stringify([data,archive,libraryView,libraryDay])};
}
async function paper(id) {
  const p = await api(`papers/${id}`);
  const contextDay=route().day;
  const bulletinDay=contextDay ? (p.bulletin_days?.includes(contextDay) ? contextDay : null) : p.bulletin_days?.[0];
  const removeFromBulletin=bulletinDay ? button("Eliminar de este boletín",async()=>{
    if(!window.confirm(`¿Eliminar este artículo del boletín del ${dayLabel(bulletinDay)}? Se conservarán el documento, su resumen y sus marcas en la biblioteca. No se cancelan tareas de resumen.`))return;
    await api(`bulletins/${bulletinDay}/papers/${id}`,{method:"DELETE"});
    if(!contextDay)location.hash=`#paper/${id}/${bulletinDay}`;
    toast("Artículo eliminado de ese boletín. Sigue disponible en la biblioteca.");
  },"danger") : null;
  if(removeFromBulletin)removeFromBulletin.title=`Eliminar del boletín del ${dayLabel(bulletinDay)}`;
  const node = el("div", {class:"paper-detail"}, el("a",{href:contextDay ? `#library/${contextDay}` : "#library",class:"back"},"← Volver a la biblioteca"),
    el("div",{class:"paper-meta"},tag(p.source==="arxiv" ? "Preprint de arXiv" : `Colibrí · ${p.document_type || "Documento"}`), ...paperTags(p),p.source==="arxiv" ? tag(`v${p.version}`) : null,date(p.updated)),
    el("h1",{class:"document-title"},p.title),el("p",{class:"authors"},p.authors.join(" · ")),
    el("div",{class:"actions"},safeLink(p.url,`Abrir en ${sourceName(p.source)} ↗`,"button primary"),pdfButton(p),
      button(p.favorite ? "★ Favorito" : "☆ Guardar favorito",()=>api(`papers/${id}`,{method:"PATCH",body:JSON.stringify({favorite:!p.favorite})})),
      button(p.is_read ? "Marcar no leído" : "Marcar leído",()=>api(`papers/${id}`,{method:"PATCH",body:JSON.stringify({is_read:!p.is_read})})),
         el("a",{href:`/api/papers/${id}/export`,class:"button"},"Exportar Markdown"),removeFromBulletin),interestControls(p));
  const panel = el("div",{class:"panel technical article-summary"});
     panel.append(el("h2",{},"Resumen"),el("section",{},el("h3",{},"Por qué puede interesarte"),el("p",{},p.brief?.relevance_reason || (p.abstract ? "Afinidad todavía no evaluada a partir del abstract y tus filtros guardados." : "No hay abstract para evaluar afinidad sin inventarla."))),
      el("section",{},el("h3",{},"Abstract original"),el("p",{},p.abstract || "No disponible en la fuente.")));
    const sectionPanel=el("section",{},el("h3",{},"Resumen de las secciones principales"));
    const supportPanel=el("section",{},el("h3",{},"Organizaciones que apoyan el estudio"));
    if(p.overview){
      for(const section of p.overview.sections) sectionPanel.append(el("div",{class:"section-summary"},el("h4",{},section.title),el("p",{},section.summary || "No se recuperó contenido suficiente de esta sección para resumirla."),el("small",{class:"coverage"},`Páginas consultadas: ${section.pages.join(", ") || "no disponibles"}`),
        section.evidence.length ? el("details",{},el("summary",{},"Ver citas del resumen"),section.evidence.map(item=>el("blockquote",{},`${item.quote} — p. ${item.page}`))) : null));
      sectionPanel.append(el("p",{class:"notice"},p.overview.warning),el("p",{class:"coverage"},`${p.overview.coverage.sections_summarized} de ${p.overview.coverage.sections_detected} secciones detectadas · Modelo: ${p.overview.stats.model}`));
      if(!p.overview.coverage.conclusion_detected)sectionPanel.append(el("p",{class:"notice warn"},"No se pudo localizar una sección de conclusión. No se ha inventado ni sustituido por el abstract."));
      supportPanel.append(p.overview.support.length ? el("ul",{},p.overview.support.map(org=>el("li",{},el("strong",{},org.name),` · ${org.role==="funding" ? "Financiación" : "Apoyo explícito"}`,el("blockquote",{},`${org.quote} — p. ${org.page}`)))) : el("p",{},p.overview.scope==="pdf_unavailable" ? "No se pudo consultar el PDF para identificar apoyos o financiación. No se deducen de las afiliaciones." : "No se identificaron organizaciones con apoyo o financiación explícitos en los extractos consultados. Esto no demuestra que no existan; las afiliaciones no se cuentan como patrocinio."));
    }else{
      sectionPanel.append(el("p",{},"Pendiente de lectura del PDF. El abstract no permite resumir las secciones ni la conclusión."));
      supportPanel.append(el("p",{},"Pendiente de revisar declaraciones de apoyo o financiación en el PDF. No se deducen de las afiliaciones."));
    }
    panel.append(sectionPanel,supportPanel);
    const job=p.jobs.find(j=>j.kind==="summary");
    if((!p.overview || (p.abstract && !p.brief) || p.overview.scope==="pdf_unavailable") && !["queued","running"].includes(job?.status))panel.append(button(job ? "Reintentar resumen" : "Generar resumen",()=>api(`papers/${id}/jobs/summary?regenerate=true`,{method:"POST"}),"primary"));
    panel.append(el("p",{class:"coverage"},"El resumen completo se prepara automáticamente para los artículos del boletín. Si el PDF no es público o legible, se indica sin inventar información."));
  if(job && job.status!=="done")panel.append(el("div",{class:job.status === "error" ? "notice warn" : "notice"},`${labels[job.status] || job.status}: ${job.error || job.progress || "Esperando al coordinador"}`,cancelButton({...job,title:p.title})));
  node.append(panel);
  return {node,data:JSON.stringify(p)};
}
async function activity() {
  const data = await api("activity");
  const node = el("div",{},hero("Actividad","Procesamiento de artículos y generación de resúmenes."));
  const limit=data.job_limit ?? settings.bulletin_limit;
  const jobs=data.jobs.slice(0,limit);
  node.append(el("div",{class:"panel",id:"processing-queue"},el("h2",{},"Artículos en procesamiento y procesados"),el("p",{class:"coverage"},`Mostrando ${jobs.length} de ${data.jobs_total ?? data.jobs.length} artículos con tareas guardadas. Máximo ${limit}, según el cupo diario del boletín; primero los que están en curso o en cola y después los más recientes.`),jobs.length ? jobs.map(job=>el("div",{class:"activity-item"},el("a",{href:`#paper/${job.paper_id}`},job.title),el("p",{},`${jobName(job.kind)} · ${labels[job.status] || job.status} · ${job.progress || ""}`),job.error ? el("p",{class:"error-text"},job.error) : null,cancelButton(job),["error","cancelled"].includes(job.status) ? button("Reintentar",()=>api(`papers/${job.paper_id}/jobs/${job.kind}`,{method:"POST"})) : null)) : el("p",{class:"muted"},"Todavía no hay artículos procesados ni en cola.")));
  return {node,data:JSON.stringify([jobs,data.jobs_total,limit])};
}
function field(label, input, hint = "") {return el("div",{class:"field"},el("label",{htmlFor:input.id},label),input,hint ? el("small",{},hint) : null);}
function interestBreakdown(proposal){
  return el("details",{class:"category-guide"},el("summary",{},"Ver desglose de intereses positivos"),
    (proposal.interests || []).map(item=>el("section",{},el("h4",{},item.topic),el("blockquote",{},item.source_text),
      item.categories ? el("p",{class:"coverage"},`Categorías: ${item.categories.join(", ") || "sin correspondencia directa"}`) : null,
      el("p",{class:"coverage"},`Términos: ${item.keywords.join(" · ") || "sin términos propuestos"}`))));
}
async function configuration() {
  const [modelData,catalog] = await Promise.all([api("models"),api("categories")]);
  models = modelData;
  Object.assign(communityNames,catalog.colibri_communities || {});
  const inputs = {};
  const input = (key,type="text") => inputs[key] = el("input",{id:key,type,value:settings[key]});
  const number = (key,min,max) => {const node=input(key,"number");node.min=min;node.max=max;return node;};
  const check = (key,label) => {inputs[key]=el("input",{id:key,type:"checkbox",checked:settings[key]});return el("label",{class:"check-label",htmlFor:key},inputs[key],label);};
  const modelNames = [...new Set([settings.model,...models.models])];
  inputs.model=el("select",{id:"model"},modelNames.map(name=>el("option",{value:name,selected:name===settings.model},name)));
  inputs.categories=el("input",{id:"categories",value:settings.categories.join(", ")});
  inputs.keywords=el("textarea",{id:"keywords",rows:4,value:settings.keywords.join("\n"),placeholder:"Un término o frase por línea"});
  inputs.excluded_keywords=el("textarea",{id:"excluded_keywords",rows:3,value:settings.excluded_keywords.join("\n")});
  inputs.interests_text=el("textarea",{id:"interests_text",rows:5,maxLength:4000,value:settings.interests_text || "",placeholder:"Intereses para arXiv. No se mezclan con los de Colibrí."});
  inputs.colibri_scopes=el("textarea",{id:"colibri_scopes",rows:3,value:settings.colibri_scopes.join("\n")});
  for(const key of ["colibri_keywords","colibri_excluded_keywords","colibri_types"]) inputs[key]=el("textarea",{id:key,rows:3,value:settings[key].join("\n"),placeholder:"Un término o tipo por línea"});
  inputs.colibri_interests_text=el("textarea",{id:"colibri_interests_text",rows:5,maxLength:4000,value:settings.colibri_interests_text || "",placeholder:"Intereses positivos para Colibrí: temas, problemas y disciplinas. Se buscan dentro de las comunidades elegidas."});
  const form=el("form",{onsubmit: event=>{event.preventDefault();action(async()=>{
    const draft={...settings};
    for (const [key,node] of Object.entries(inputs)) draft[key]=node.type==="checkbox" ? node.checked : node.type==="number" ? Number(node.value) : node.value;
    for(const key of ["categories","keywords","excluded_keywords","colibri_scopes","colibri_keywords","colibri_excluded_keywords","colibri_types"]) draft[key]=draft[key].split(/[,\n]/).map(word=>word.trim()).filter(Boolean);
    settings=await api("settings",{method:"PUT",body:JSON.stringify(draft)});
    toast("Configuración guardada. El modelo se aplica a las próximas tareas.");
  });}});
  const preview=el("div",{class:"interest-preview",role:"status"});
  const save=el("button",{type:"submit",class:"primary"},"Guardar configuración");
  const propose=el("button",{type:"button",class:"primary",onclick:async()=>{
    const text=inputs.interests_text.value.trim();
    if(text.length<3){toast("Describe primero tus intereses.",true);return;}
    propose.disabled=true;proposeColibri.disabled=true;save.disabled=true;inputs.interests_text.disabled=true;propose.textContent="Proponiendo filtros…";
    try{
      const result=await api("interests/propose",{method:"POST",body:JSON.stringify({text})});
      const p=result.proposal;
      preview.replaceChildren(el("p",{lang:"en"},p.explanation),interestBreakdown(p),...p.warnings.map(w=>el("p",{class:"notice warn",lang:"en"},w)),el("p",{class:"coverage"},`${p.categories.length} categorías · ${p.keywords.length} términos · ${result.stats.model}${result.cached ? " · propuesta recuperada de disco" : ""}`));
      if(p.categories.length){
        inputs.categories.value=p.categories.join(", ");inputs.keywords.value=p.keywords.join("\n");
        toast("Intereses positivos cargados. Se conservaron las exclusiones manuales y la opción de coincidencia obligatoria. Revisa y guarda para aplicar.");
      }else toast("No se sustituyeron los filtros: la propuesta no tiene categorías apropiadas.",true);
    }catch(error){toast(error.message,true);}
    finally{propose.disabled=false;proposeColibri.disabled=false;save.disabled=false;inputs.interests_text.disabled=false;propose.textContent="Proponer filtros";}
  }},"Proponer filtros");
  const colibriPreview=el("div",{class:"interest-preview",role:"status"});
  const proposeColibri=el("button",{type:"button",class:"primary",onclick:async()=>{
    const text=inputs.colibri_interests_text.value.trim();if(text.length<3){toast("Describe primero tus intereses para Colibrí.",true);return;}
    proposeColibri.disabled=true;propose.disabled=true;save.disabled=true;inputs.colibri_interests_text.disabled=true;proposeColibri.textContent="Proponiendo términos…";
    try{
      const result=await api("interests/propose",{method:"POST",body:JSON.stringify({text,source:"colibri"})});const p=result.proposal;
      inputs.colibri_keywords.value=p.keywords.join("\n");
      colibriPreview.replaceChildren(el("p",{lang:"es"},p.explanation),interestBreakdown(p),...p.warnings.map(w=>el("p",{class:"notice warn",lang:"es"},w)),el("p",{class:"coverage"},`${p.keywords.length} términos · ${result.stats.model}${result.cached ? " · recuperada de disco" : ""}`));
      toast("Términos de Colibrí propuestos. Revísalos y guarda para aplicarlos; no se modificaron los filtros de arXiv.");
    }catch(error){toast(error.message,true);}
    finally{proposeColibri.disabled=false;propose.disabled=false;save.disabled=false;inputs.colibri_interests_text.disabled=false;proposeColibri.textContent="Proponer términos de Colibrí";}
  }},"Proponer términos de Colibrí");
  const scopeBrowser=el("div",{class:"scope-browser"});
  const scopeSummary=el("p",{class:"coverage"});
  const updateScopes=()=>{scopeSummary.textContent=inputs.colibri_scopes.value.split(/[,\n]/).map(x=>x.trim()).filter(Boolean).map(x=>communityNames[x] || x).join(" · ");};
  inputs.colibri_scopes.addEventListener("input",updateScopes);updateScopes();
  const browseScopes=async(parent=null)=>{
    const data=await api("colibri/scopes",{method:"POST",body:JSON.stringify({parent})});
    scopeBrowser.replaceChildren(parent ? draftButton("← Comunidades principales",()=>browseScopes()) : el("p",{},"Comunidades principales"),...data.entries.map(entry=>{
      communityNames[entry.uuid]=entry.name;
      return el("div",{class:"scope-row"},el("span",{},entry.name),draftButton("Añadir",()=>{
        const chosen=inputs.colibri_scopes.value.split(/[,\n]/).map(x=>x.trim()).filter(Boolean);if(!chosen.includes(entry.uuid))chosen.push(entry.uuid);inputs.colibri_scopes.value=chosen.join("\n");updateScopes();
      }),entry.kind==="communities" ? draftButton("Ver contenido",()=>browseScopes(entry.uuid)) : tag("Colección"));
    }));
  };
  const categoryGuide=el("details",{class:"category-guide"},el("summary",{},"Ver categorías disponibles"),el("ul",{},Object.entries(catalog.categories).map(([code,label])=>el("li",{},el("code",{},code)," · ",label))));
  form.append(el("div",{class:"settings-grid"},
    el("section",{class:"panel source-settings"},el("h2",{},"Colibrí · filtros propios"),check("colibri_enabled","Seguir Colibrí"),
      field("Comunidades y colecciones elegidas (UUID)",inputs.colibri_scopes,"Fing incluye InCo: no se repiten consultas ni documentos por seleccionar ambos. Puedes añadir desde el catálogo o quitar una línea."),scopeSummary,
      draftButton("Explorar comunidades de Colibrí",()=>browseScopes()),scopeBrowser,
      field("Intereses en tus palabras · Colibrí",inputs.colibri_interests_text,"Hasta 4000 caracteres. La propuesta usa las comunidades guardadas; no las elige por ti."),proposeColibri,colibriPreview,
      field("Términos de Colibrí",inputs.colibri_keywords,"Título, abstract y materias. Sin tope fijo de cantidad; basta una coincidencia si activas el requisito."),check("colibri_keyword_filter","Exigir coincidencia de término para seleccionar el boletín de Colibrí"),
      field("Excluir términos · Colibrí (manual)",inputs.colibri_excluded_keywords,"Separados de los intereses positivos. El modelo no los propone ni modifica. Solo afecta al boletín, no elimina registros."),field("Tipos de documento",inputs.colibri_types,"Vacío: todos. Por ejemplo: Artículo, Tesis de grado, Tesis de maestría, Tesis de doctorado. Coincidencia exacta sin distinguir mayúsculas."),
      el("div",{class:"notice"},"Novedades por fecha de depósito, no por año de publicación. El boletín prepara un único resumen por documento; el PDF debe ser público y legible para resumir secciones y apoyos.")),
    el("section",{class:"panel source-settings"},el("h2",{},"arXiv · filtros propios"),check("arxiv_enabled","Seguir arXiv"),field("Intereses en tus palabras · arXiv",inputs.interests_text,"La propuesta no usa intereses ni marcas de Colibrí."),propose,preview,
      field("Categorías de arXiv",inputs.categories,"Sin tope fijo de cantidad, dentro del catálogo; separadas por comas. Un interés puede usar varias categorías."),categoryGuide,field("Términos de arXiv",inputs.keywords,"Sin tope fijo de cantidad. Se comparan con título y abstract; son alternativas OR."),check("keyword_filter","Exigir coincidencia de término en la consulta a arXiv"),el("small",{},"Desactivado: solo priorizan el boletín. Activado: filtran también la consulta a arXiv. Proponer intereses no cambia esta opción."),field("Excluir términos · arXiv (manual)",inputs.excluded_keywords,"Separados de los intereses positivos. El modelo no los propone ni modifica. Solo afecta al boletín.")),
    el("section",{class:"panel"},el("h2",{},"Modelo y presupuesto"),field("Modelo local de Ollama",inputs.model,models.available ? "No se descargan modelos automáticamente." : "Ollama no responde. Los trabajos pendientes se conservan."),field("Resúmenes automáticos totales por día",number("bulletin_limit",1,30)),field("Tamaño máximo de PDF (MB)",number("max_pdf_mb",1,250),"100 MB por defecto. Es el límite de descarga, no el contexto del modelo ni el número de páginas consultadas."),field("Máximo de secciones por documento",number("max_chunks",1,40),"Cada petición usa extractos acotados. La conclusión se prioriza si se identifica; la cobertura parcial se indica."),check("unload_after_paper","Liberar el modelo de RAM al terminar cada resumen"),check("pause_summaries","Pausar la generación de resúmenes")),
     el("section",{class:"panel"},el("h2",{},"Horario diario y reparto"),field("Resúmenes diarios reservados a Colibrí",number("colibri_bulletin_limit",0,30),"Del total diario de resúmenes, el resto se reserva a arXiv. Recomendación inicial: 8 de 10."),field("Periodo inicial (días)",number("initial_days",1,30)),field("Hora local",input("daily_time","time")),field("Zona horaria",input("timezone"),"Formato IANA, por ejemplo America/Montevideo."),field("Solapamiento de metadatos (días)",number("metadata_overlap_days",3,30),"Se deduplican los documentos. Cambiar filtros reinicia solo el cursor de esa fuente y respeta sus pausas de red."),check("schedule_enabled","Activar búsquedas automáticas"),el("p",{class:"subtitle"},"Los cupos son máximos por día, incluso con varias búsquedas manuales. Si faltan novedades de una fuente, no se rellena con la otra. Las marcas de interés no alteran búsquedas ni rellenan cupos.")),
     el("section",{class:"panel"},el("h2",{},"Notificaciones y privacidad"),check("desktop_notifications","Avisar al completar un resumen"),el("p",{class:"subtitle"},"Un aviso nativo de Linux por resumen terminado, incluso con la pestaña cerrada."),button("Probar notificación",async()=>{await api("notifications/test",{method:"POST"});toast("Aviso enviado al escritorio.");}),el("p",{class:"subtitle spacer"},"Solo destinos oficiales de arXiv y Colibrí. Ollama no recibe herramientas. Las marcas de interés no se envían al modelo. Las solicitudes externas quedan contadas por fuente; se respeta Retry-After y se aumenta la pausa ante 429/503."),el("div",{class:"notice warn"},"Un resumen automático no reemplaza una revisión científica. No hay OCR; tablas, figuras o fórmulas pueden perder información. No se inicia sesión ni se eluden restricciones de Colibrí."))));
  form.append(el("div",{class:"form-actions"},save));
  const distribution=el("p",{class:"notice",id:"daily-distribution"});
  const showDistribution=()=>{
    const cb=inputs.colibri_enabled.checked ? Number(inputs.colibri_bulletin_limit.value) : 0;
    const ab=inputs.arxiv_enabled.checked ? Math.max(0,Number(inputs.bulletin_limit.value)-cb) : 0;
    distribution.textContent=`Reparto diario: hasta ${cb} resúmenes de Colibrí + ${ab} de arXiv. Los cupos no utilizados no se transfieren.`;
  };
  for(const key of ["colibri_enabled","arxiv_enabled","bulletin_limit","colibri_bulletin_limit"]) inputs[key].addEventListener("input",showDistribution);
  showDistribution();form.prepend(distribution);
  return {node:el("div",{},hero("Configuración","Filtros, horario y presupuesto de procesamiento."),form),data:JSON.stringify([settings,models])};
}
function route(){const parts=(location.hash.slice(1)||"home").split("/");return {view:parts[0],id:parts[1],day:parts[2]};}
async function render(force=false) {
  if(rendering) return;
  rendering=true;
  const initialHash=location.hash;
  try {
    const {view,id}=route();
    const builders={home,library,activity,settings:configuration,paper:()=>paper(id)};
    const result=await (builders[view]||home)();
    if(location.hash!==initialHash) { fingerprint="";return; }
    const next=`${location.hash}|${result.data}`;
    if(force || next!==fingerprint) {
      const active=document.activeElement;
      const selection=active?.type==="search" ? {start:active.selectionStart,end:active.selectionEnd} : null;
      $("#content").replaceChildren(result.node);
      if(selection && view==="library") {const input=$(".filters input");input.focus();input.setSelectionRange(selection.start,selection.end);}
      fingerprint=next;
    }
    $("main").dataset.view=view;
    $("#breadcrumb").textContent=names[view]||names.home;
    document.querySelectorAll("nav a").forEach(link=>link.classList.toggle("active",link.dataset.view===(view==="paper"?"library":view)));
  } catch(error) {toast(error.message,true);}
  finally {rendering=false;if(location.hash!==initialHash) render(true);}
}
function processingStatus(state){
  const job=state.current_job;
  const busy=!!job || state.scanning || state.compiling_interests;
  let completed=job?.progress_completed,total=job?.progress_total;
  if(total===undefined){
    const reading=job?.progress?.match(/Leyendo fragmento (\d+)\/(\d+)/);
    const confirmed=job?.progress?.match(/Fragmentos confirmados (\d+)\/(\d+)/);
    const match=reading || confirmed;
    if(match){completed=Math.max(0,Number(match[1])-(reading ? 1 : 0));total=Number(match[2]);}
  }
  const known=Number.isFinite(completed) && Number.isFinite(total) && total>0;
  const value=known ? Math.max(0,Math.min(1,completed/total)) : 0;
  const indicator=$("#progress-indicator");indicator.className=`progress-indicator${busy && !known ? " indeterminate" : ""}`;
  const unit=job?.progress_unit || "fragmentos";
  indicator.setAttribute("role",busy ? "progressbar" : "img");indicator.setAttribute("aria-label",known ? `${completed} de ${total} ${unit} confirmados` : busy ? "Procesamiento en curso; avance todavía no medible" : "Sin tareas en curso");
  for(const key of ["aria-valuenow","aria-valuemin","aria-valuemax"]) indicator.removeAttribute(key);
  if(known){indicator.setAttribute("aria-valuemin","0");indicator.setAttribute("aria-valuemax","100");indicator.setAttribute("aria-valuenow",String(Math.round(value*100)));}
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("viewBox","0 0 44 44");svg.setAttribute("aria-hidden","true");
  for(const cls of ["progress-track","progress-arc"]){const circle=document.createElementNS(svg.namespaceURI,"circle");for(const [key,val] of Object.entries({cx:22,cy:22,r:18,class:cls}))circle.setAttribute(key,String(val));if(cls==="progress-arc"){circle.setAttribute("stroke-dasharray",String(2*Math.PI*18));circle.setAttribute("stroke-dashoffset",String(2*Math.PI*18*(1-value)));}svg.appendChild(circle);}
  indicator.replaceChildren(svg,el("span",{class:"progress-number"},known ? `${Math.round(value*100)}%` : ""));
  $("#statusbar").textContent=state.unavailable ? "Servicio no disponible" : job?.cancel_requested ? "Cancelando tarea…" : state.compiling_interests ? "Proponiendo filtros de intereses…" : job ? job.progress || "Procesando documento…" : state.scanning ? "Buscando novedades…" : "Sin tareas en curso";
  const title=$("#processing-title");title.hidden=!job;title.textContent=job?.title || "";title.title=job?.title || "";if(job)title.href=`#paper/${job.paper_id}`;else title.removeAttribute("href");
  const count=$("#progress-count");count.hidden=!known;count.textContent=known ? `${completed}/${total} ${unit} ${unit==="secciones" ? "confirmadas" : "confirmados"}` : "";
}
async function refresh(force=false) {
  try {
    [status,settings]=await Promise.all([api("status"),api("settings")]);
    processingStatus(status);
    if(force || !["settings","library"].includes(route().view)) await render(force);
  }catch(error){processingStatus({unavailable:true});}
}
window.addEventListener("hashchange",()=>{fingerprint="";render(true);});
refresh(true);
setInterval(()=>{if(!document.hidden)refresh();},10000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh();});
