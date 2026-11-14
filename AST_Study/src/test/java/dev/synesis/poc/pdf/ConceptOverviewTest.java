package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.ui.MistWorkspaceTheme;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.event.HyperlinkEvent;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicReference;

/** Offline presentation checks. Saved fixtures must be copies; no generation/API entry points are called. */
public final class ConceptOverviewTest {
    private record Fixture(PdfWorkspace workspace,JsonObject saved,String original,ConceptOverview overview,JPanel frame,JPanel list,JScrollPane scroll) {}
    public static void main(String[] args)throws Exception {
        Path output=Files.createTempDirectory("synesis-concept-design-check-");
        for(String arg:args)checkSaved(Path.of(arg),output);
        edt(()->{checkDuplicateIdentities();return null;});
        System.out.println("ConceptOverviewTest passed: collapsed entry, lazy/cached bodies, refresh/resize, sparse page labels, search, existing scope/menu/navigation and selection provenance. Renders: "+output);
        System.exit(0);
    }
    private static void checkSaved(Path folder,Path output)throws Exception {
        Fixture f=edt(()->open(folder));
        try {
            edt(()->{
                List<ConceptOverview.Card> cards=cards(f);require(cards.size()==f.saved.getAsJsonArray("concepts").size(),"concept count changed");
                require(editors(f.list).isEmpty(),"initial entry must not render closed bodies");
                for(int i=0;i<cards.size();i++){
                    require(cards.get(i).getHeight()==56,"collapsed Figma row height changed: "+cards.get(i).getHeight());
                    String name=f.saved.getAsJsonArray("concepts").get(i).getAsJsonObject().get("name").getAsString();
                    require(button(cards.get(i),name)!=null,"concept order/name changed");
                }
                snapshot(f,output.resolve(folder.getFileName()+"-collapsed.png"));
                toggle(cards.getFirst()).doClick();layout(f.frame);
                require(!editors(cards.getFirst()).isEmpty(),"expand did not render body");
                return null;
            });drain();
            List<JEditorPane> initial=edt(()->editors(cards(f).getFirst()));
            edt(()->{refresh(f);layout(f.frame);require(editors(cards(f).getFirst()).equals(initial),"unchanged update rebuilt body");f.frame.setSize(400,900);layout(f.frame);return null;});drain();
            edt(()->{
                require(editors(cards(f).getFirst()).equals(initial),"resize rebuilt body");
                snapshot(f,output.resolve(folder.getFileName()+"-open-narrow.png"));f.frame.setSize(648,900);layout(f.frame);
                f.scroll.getViewport().setViewPosition(new Point(0,Math.min(240,Math.max(0,f.list.getHeight()-f.scroll.getViewport().getHeight()))));
                return null;
            });drain();
            ConceptOverview.Bookmark anchor=edt(f.overview::capture);
            edt(()->{refresh(f);layout(f.frame);return null;});drain();
            edt(()->{
                var current=f.overview.capture();require(Objects.equals(anchor.key(),current.key())&&Math.abs(anchor.offset()-current.offset())<=2,"data refresh changed reading position: "+anchor+" -> "+current);
                require(editors(cards(f).getFirst()).equals(initial),"refresh did not reuse open body");
                @SuppressWarnings("unchecked") Map<String,StudySelectionContext.Source> sources=(Map<String,StudySelectionContext.Source>)field(f.workspace,"conceptSelectionSources");
                StudyHtmlPane pane=(StudyHtmlPane)initial.getFirst();require(pane.getClientProperty(StudySelectionActions.class)!=null,"selection actions detached");
                pane.setStudySelection(2,Math.min(pane.getDocument().getLength(),25));
                JsonObject context=StudySelectionContext.capture(List.of(pane),"검사 선택","개념",sources);
                require(context.has("title")&&context.has("pages"),"refresh lost source-aware tutor selection: "+context);
                f.overview.search.setText(f.saved.getAsJsonArray("concepts").get(0).getAsJsonObject().get("name").getAsString());filter(f.overview);
                require(cards(f).getFirst().isVisible(),"search hid matching concept");
                require(cards(f).stream().filter(Component::isVisible).count()<cards(f).size(),"search not connected");
                require(editors(cards(f).getFirst()).equals(initial),"search rebuilt body");
                f.overview.search.setText("");filter(f.overview);layout(f.frame);
                require(cards(f).stream().allMatch(Component::isVisible),"cleared search lost concepts");
                List<ConceptOverview.Card> originalCards=cards(f);
                JsonObject update=f.saved.deepCopy();update.getAsJsonArray("concepts").get(1).getAsJsonObject().getAsJsonArray("entries").get(0).getAsJsonObject().addProperty("example","갱신 확인용 예시");
                set(f.workspace,"generated",update);refresh(f);layout(f.frame);
                require(cards(f).equals(originalCards),"local update replaced row identities");
                require(editors(cards(f).getFirst()).equals(initial),"unrelated concept update rebuilt current body");
                set(f.workspace,"generated",f.saved);refresh(f);layout(f.frame);
                toggle(cards(f).getFirst()).doClick();toggle(cards(f).getFirst()).doClick();
                require(editors(cards(f).getFirst()).equals(initial),"collapse/reopen rerendered unchanged body");
                JButton more=button(f.overview,"개념정리 도구");JPopupMenu menu=more.getComponentPopupMenu();
                require(menu!=null&&menu.getComponent(0) instanceof JMenu versions&&versions.getItemCount()>1,"version options missing from more menu");
                for(var listener:menu.getPopupMenuListeners())listener.popupMenuWillBecomeVisible(new javax.swing.event.PopupMenuEvent(menu));
                require(Arrays.stream(menu.getComponents()).filter(c->c instanceof JMenuItem item&&item.getText().contains("처리")).count()>0,"existing processing-history action missing");
                snapshot(f,output.resolve(folder.getFileName()+"-open.png"));
                // A real saved page link must still call the existing local PDF navigation.
                int target=Math.min(2,((PdfSource)field(f.workspace,"source")).count);
                HyperlinkEvent event=new HyperlinkEvent(pane,HyperlinkEvent.EventType.ACTIVATED,null,"page:"+target);
                for(var listener:pane.getHyperlinkListeners())listener.hyperlinkUpdate(event);
                require((int)field(f.workspace,"page")==target,"original PDF navigation disconnected");
                @SuppressWarnings("unchecked") Map<String,JsonObject> products=(Map<String,JsonObject>)field(f.workspace,"products");
                JsonObject pageResult=f.saved.deepCopy();pageResult.addProperty("scope","page");pageResult.addProperty("page",target);products.put("new-concept-v99:page:"+target,pageResult);
                JComboBox<?> scope=(JComboBox<?>)field(f.workspace,"scope");scope.setSelectedIndex(1);
                require(field(f.workspace,"generated")==pageResult,"existing scope product selection changed");
                scope.setSelectedIndex(0);require(field(f.workspace,"generated")==f.saved,"document scope not restored");
                require(f.saved.toString().equals(f.original),"display mutated original saved result");
                return null;
            });drain();
            System.out.println(folder.getFileName()+": "+f.saved.getAsJsonArray("concepts").size()+" concepts preserved; cached bodies, source context, scope, navigation and scroll passed");
        }finally{edt(()->{f.workspace.close();return null;});}
    }
    private static Fixture open(Path folder)throws Exception {
        JsonObject saved=JsonParser.parseString(Files.readString(folder.resolve("latest-document-0.json"))).getAsJsonObject();String original=saved.toString();Path work=Files.createTempDirectory("concept-fixture-");
        PdfWorkspace workspace=new PdfWorkspace(false,work);PdfSource source=PdfSource.open(folder.resolve("source.pdf"),work);
        set(workspace,"source",source);set(workspace,"index",JsonParser.parseString(Files.readString(folder.resolve("document.json"))).getAsJsonObject());set(workspace,"generated",saved);
        @SuppressWarnings("unchecked") Map<String,JsonObject> products=(Map<String,JsonObject>)field(workspace,"products");products.put("new-concept-v99:document:0",saved);
        Method show=PdfWorkspace.class.getDeclaredMethod("showConcepts");show.setAccessible(true);show.invoke(workspace);workspace.showConceptSummary();
        ConceptOverview overview=(ConceptOverview)field(workspace,"conceptOverview");JPanel list=(JPanel)field(workspace,"conceptList");JScrollPane scroll=(JScrollPane)field(workspace,"conceptScroll");
        JPanel frame=new MistWorkspaceTheme.Panel(new BorderLayout(),12,Color.WHITE,MistWorkspaceTheme.LINE);frame.add(overview);overview.setVisible(true);frame.setSize(648,900);layout(frame);
        return new Fixture(workspace,saved,original,overview,frame,list,scroll);
    }
    private static void checkDuplicateIdentities()throws Exception {
        PdfWorkspace workspace=new PdfWorkspace(false,Files.createTempDirectory("concept-duplicates-"));
        try {
            JsonObject saved=JsonParser.parseString("""
                {"strategy":"new-concept-v99","scope":"document","page":0,"concepts":[
                 {"name":"같은 이름","pages":[3,8],"entries":[{"definition":"서로 다른 첫 설명","evidence":[{"sourceId":"region-a","page":3},{"sourceId":"region-c","page":8}]}]},
                 {"name":"같은 이름","pages":[4],"entries":[{"definition":"서로 다른 둘째 설명","evidence":[{"sourceId":"region-b","page":4}]}]},
                 {"name":"같은 이름","pages":[4],"entries":[{"definition":"통합하지 않을 셋째 설명","evidence":[{"sourceId":"region-b","page":4}]}]}]}
                """).getAsJsonObject();
            set(workspace,"generated",saved);Method show=PdfWorkspace.class.getDeclaredMethod("showConcepts");show.setAccessible(true);show.invoke(workspace);
            @SuppressWarnings("unchecked") Map<String,ConceptOverview.Card> map=(Map<String,ConceptOverview.Card>)field(workspace,"conceptCards");require(map.size()==3,"same names/provenance merged distinct saved concepts");
            ConceptOverview.Card first=map.values().iterator().next();require(button(first,"원문 이동: p.3 · p.8")!=null,"nonconsecutive pages presented as a range");
            toggle(first).doClick();require(!editors(first).isEmpty(),"duplicate fixture body missing");
        }finally{workspace.close();}
    }
    private static List<ConceptOverview.Card> cards(Fixture f)throws Exception{
        @SuppressWarnings("unchecked") Map<String,ConceptOverview.Card> cards=(Map<String,ConceptOverview.Card>)field(f.workspace,"conceptCards");return new ArrayList<>(cards.values());
    }
    private static JButton toggle(ConceptOverview.Card card){for(Component child:card.getComponents())if(child instanceof Container nested)for(Component control:nested.getComponents())if(control instanceof JButton button&&button.getAccessibleContext().getAccessibleName()!=null&&!button.getAccessibleContext().getAccessibleName().startsWith("원문 이동:"))return button;throw new AssertionError("toggle missing");}
    private static JButton button(Container root,String name){for(Component child:root.getComponents()){if(child instanceof JButton button&&name.equals(button.getAccessibleContext().getAccessibleName()))return button;if(child instanceof Container nested){JButton found=button(nested,name);if(found!=null)return found;}}return null;}
    private static List<JEditorPane> editors(Container root){List<JEditorPane> out=new ArrayList<>();for(Component child:root.getComponents())if(child instanceof JEditorPane pane)out.add(pane);else if(child instanceof Container nested)out.addAll(editors(nested));return out;}
    private static void filter(ConceptOverview overview)throws Exception{Method m=ConceptOverview.class.getDeclaredMethod("filter");m.setAccessible(true);m.invoke(overview);}
    private static Object field(Object owner,String name)throws Exception{Field field=owner.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(owner);}
    private static void set(Object owner,String name,Object value)throws Exception{Field field=owner.getClass().getDeclaredField(name);field.setAccessible(true);field.set(owner,value);}
    private static void refresh(Fixture f)throws Exception{Method m=PdfWorkspace.class.getDeclaredMethod("showConcepts");m.setAccessible(true);m.invoke(f.workspace);}
    private static void layout(Container root){for(int i=0;i<5;i++)layoutTree(root);}
    private static void layoutTree(Container root){root.invalidate();root.doLayout();for(Component child:root.getComponents())if(child instanceof Container nested&&child.isVisible())layoutTree(nested);}
    private static void snapshot(Fixture f,Path path)throws Exception{layout(f.frame);BufferedImage image=new BufferedImage(f.frame.getWidth(),f.frame.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());f.frame.printAll(g);g.dispose();ImageIO.write(image,"png",path.toFile());}
    private static <T> T edt(Callable<T> action)throws Exception{AtomicReference<T> result=new AtomicReference<>();AtomicReference<Throwable> error=new AtomicReference<>();SwingUtilities.invokeAndWait(()->{try{result.set(action.call());}catch(Throwable t){error.set(t);}});if(error.get()!=null)throw new AssertionError(error.get());return result.get();}
    private static void drain()throws Exception{edt(()->null);edt(()->null);}
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
