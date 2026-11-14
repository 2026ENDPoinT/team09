package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.text.*;
import javax.swing.text.html.*;

/** Offline rendering/resize contracts for the reading skin; never calls a model or changes saved results. */
public final class SummaryReadingSkinTest {
    private static final Path OUT=Path.of("build/summary-skin-20261017");
    private static final String CONTENT="""
        손익계산서는 일정한 기간 동안 기업이 올린 매출과 발생한 비용, 그리고 그 차이로 남은 이익을 정리해요.

        > 매출액 − 비용 = 당기순이익

        1. **매출액**\n   상품과 서비스를 판매해서 얻은 전체 금액이에요.
        2. **비용**\n   상품 생산과 영업, 이자 및 세금 등에 사용한 금액이에요.
        3. **당기순이익**\n   모든 비용을 제외하고 해당 기간에 최종적으로 남은 이익이에요.

        | 구분 | 계산 기준 | 금액 |
        | :--- | :--- | ---: |
        | EBIT | 이자 및 세전이익 | 100 |
        | 세전이익 | 100 − 20 | 80 |
        | 법인세 | 80 × 25% | 20 |
        | 당기순이익 | 80 − 20 | **60** |

        운동량은 \\(p=mv\\)이고 다음 관계가 성립해요.

        $$p_1+p_2=p_{\\mathrm{total}}$$

        ```text
        1. 이 줄은 번호 카드로 바꾸면 안 되는 코드예요.
        > 이 줄도 코드 안의 인용 기호예요.
        <table>외부 HTML은 실행하지 않아요.</table>
        ```
        """+"\n문단에 이어지는 독립 수식도 강조해요.\n\\[\\mathrm{LONGMATH}+"
            +String.join("+",java.util.stream.IntStream.rangeClosed(1,35).mapToObj(i->"p_{"+i+"}").toList())+"=0\\]\n";

    public static void main(String[] args)throws Exception {
        Files.createDirectories(OUT);
        try {SwingUtilities.invokeAndWait(()->{try {run();}catch(Exception e){throw new RuntimeException(e);}});}
        catch(Throwable failure) {failure.printStackTrace();System.exit(1);}
        System.out.println("SummaryReadingSkinTest passed");System.exit(0);
    }
    private static String body(PdfWorkspace workspace,int copies,boolean skin)throws Exception {
        StringBuilder body=new StringBuilder("<div class='study-overview'><h2>이 강의의 흐름</h2>"
            +"<p>기업의 수익과 비용을 비교하고, 재무제표를 읽는 기준을 연결해요.</p>"
            +"<p class='muted'>원문 근거 <a href='page:1'>p.1</a> &nbsp; <a href='page:2'>p.2</a></p></div>");
        Method easy=PdfWorkspace.class.getDeclaredMethod("summaryEasyBlock",JsonObject.class,String.class);easy.setAccessible(true);
        JsonObject section=new JsonObject();section.addProperty("easyExplanation","가계부에서 들어온 돈과 나간 돈을 구분하는 것처럼 생각해보세요.");
        for(int i=0;i<copies;i++) {
            if(skin)body.append("<!--READINGBREAK-->");
            body.append("<a name='synesis-summary-content'></a><h3>").append(i+1)
                .append(". 손익계산서 <a href='page:2'>p.2</a></h3>")
                .append(StudyMarkdown.renderWithScrollableMath(CONTENT,14))
                .append(easy.invoke(workspace,section,"fixture/"+i));
        }
        return body.toString();
    }
    @SuppressWarnings("unchecked")
    private static void run()throws Exception {
        easyHeaderActions();
        PdfWorkspace workspace=new PdfWorkspace(false,OUT.resolve("unused-library"));
        try {
            set(workspace,"summaryReadingSkin",true);
            ((JSlider)get(workspace,"summaryFontSize")).setValue(14);
            JScrollPane scroll=(JScrollPane)get(workspace,"summaryScroll");
            JPanel flow=(JPanel)get(workspace,"summaryFlow");
            Method render=PdfWorkspace.class.getDeclaredMethod("renderSummaryContent",String.class,Map.class);render.setAccessible(true);
            String skinBody=body(workspace,1,true);
            render.invoke(workspace,skinBody,Map.of());layout(scroll,flow,646);
            List<StudyHtmlPane> prose=prose(flow);
            check(prose.size()>1,"sections were not bounded into reusable prose documents");
            String text=text(flow);
            for(String phrase:List.of("매출액 − 비용 = 당기순이익","100 − 20","외부 HTML은 실행하지 않아요.","당기순이익"))
                check(text.contains(phrase),"source content lost: "+phrase);
            check(SummaryPageNavigator.find(flow,2)!=null,"page navigation lost after skinning");
            int cards=0,lists=0,chips=0;
            for(StudyHtmlPane pane:prose) {
                Map<String,Integer> counts=new HashMap<>();views(pane.getUI().getRootView(pane),counts);
                cards+=counts.getOrDefault("CardView",0);lists+=counts.getOrDefault("NumberedListView",0);chips+=counts.getOrDefault("CitationView",0);
            }
            StudyHtmlPane small=new StudyHtmlPane(true);small.setReadingSkin(true);small.setEditable(false);
            small.setText(SummarySkin.document("",StudyMarkdown.render("4. 첫 단계\n   1. 하위 단계\n5. 다음 단계\n\n"
                +"| 열 | 값 |\n|---|---|\n| 이름 | AccountingFinancialStatementWithLongUnbrokenName |",14),14));
            small.setSize(340,Short.MAX_VALUE);small.modelToView2D(small.getDocument().getLength());
            HTMLDocument smallDoc=(HTMLDocument)small.getDocument();
            Element ordered=find(smallDoc.getDefaultRootElement(),HTML.Tag.OL);
            check(ordered!=null,"ordered list lost");
            check("4".equals(String.valueOf(ordered.getAttributes().getAttribute(HTML.Attribute.START))),"list start renumbered");
            String smallText=smallDoc.getText(0,smallDoc.getLength());
            int tokenEnd=smallText.indexOf("UnbrokenName")+"UnbrokenName".length()-1;
            check(small.modelToView2D(tokenEnd).getMaxX()<340,"narrow table clipped a long token");
            check(cards>=3&&lists==1&&chips>=3,"native decorations missing or code incorrectly interpreted");
            for(StudyHtmlPane pane:prose) {
                HTMLDocument doc=(HTMLDocument)pane.getDocument();
                for(HTMLDocument.Iterator it=doc.getIterator(HTML.Tag.A);it.isValid();it.next())
                    if("page:2".equals(it.getAttributes().getAttribute(HTML.Attribute.HREF))) {
                        var at=pane.modelToView2D(it.getStartOffset());
                        int offset=pane.viewToModel2D(new Point((int)at.getX()+6,(int)at.getCenterY()));
                        check(offset>=it.getStartOffset()&&offset<=it.getEndOffset(),"page chip hit testing moved off its link");
                    }
            }
            long[] revisions=prose.stream().mapToLong(StudyHtmlPane::contentRevision).toArray();
            render.invoke(workspace,skinBody,Map.of());layout(scroll,flow,646);
            for(int i=0;i<prose.size();i++)check(prose.get(i).contentRevision()==revisions[i],"unchanged content reparsed");
            snapshot(flow,OUT.resolve("reading-wide.png"),646,Math.min(2100,flow.getHeight()));
            layout(scroll,flow,340);snapshot(flow,OUT.resolve("reading-narrow.png"),340,Math.min(2400,flow.getHeight()));
            for(StudyHtmlPane pane:prose) {
                var last=pane.modelToView2D(pane.getDocument().getLength());
                check(last==null||last.getMaxY()<=pane.getHeight()+2,"narrow layout clipped the final line");
            }
            for(int i=0;i<prose.size();i++)check(prose.get(i).contentRevision()==revisions[i],"width-only resize reparsed a document");
            // Expanding a known field changes its pane, not unrelated sections.
            ((Set<String>)get(workspace,"expandedEasySummaries")).add("fixture/0");
            render.invoke(workspace,body(workspace,1,true),Map.of());layout(scroll,flow,646);
            check(text(flow).contains("가계부"),"easy explanation did not expand");
            check(prose.get(0).contentRevision()==revisions[0],"easy expansion rebuilt the overview");
            snapshot(flow,OUT.resolve("reading-expanded.png"),646,Math.min(2200,flow.getHeight()));
            set(workspace,"summaryReadingSkin",false);
            render.invoke(workspace,body(workspace,1,false),Map.of());layout(scroll,flow,646);
            check(text(flow).contains("당기순이익"),"rollback lost stored content");
            for(StudyHtmlPane pane:prose(flow)) {
                Map<String,Integer> counts=new HashMap<>();views(pane.getUI().getRootView(pane),counts);
                check(!counts.containsKey("NumberedListView")&&!counts.containsKey("CardView"),"skin views leaked into rollback");
            }
            snapshot(flow,OUT.resolve("legacy.png"),646,Math.min(2100,flow.getHeight()));
            Map<String,Object> perf=new LinkedHashMap<>();
            for(boolean skin:new boolean[]{false,true}) {
                set(workspace,"summaryReadingSkin",skin);
                render.invoke(workspace,body(workspace,13,skin),Map.of());layout(scroll,flow,620);
                check(text(flow).split("LONGMATH",-1).length-1==13,"repeated wide equations were dropped by component reuse");
                List<StudyHtmlPane> panes=prose(flow);
                long[] before=panes.stream().mapToLong(StudyHtmlPane::contentRevision).toArray();
                List<Double> resize=new ArrayList<>(),paint=new ArrayList<>();
                BufferedImage viewport=new BufferedImage(700,700,BufferedImage.TYPE_INT_RGB);
                for(int i=0;i<40;i++) {
                    int width=620-(i%20)*12;
                    long start=System.nanoTime();layout(scroll,flow,width);
                    resize.add((System.nanoTime()-start)/1e6);
                    Graphics2D g=viewport.createGraphics();
                    int y=(i*220)%Math.max(1,flow.getHeight()-700);g.translate(0,-y);g.setClip(0,y,width,700);
                    start=System.nanoTime();flow.paint(g);paint.add((System.nanoTime()-start)/1e6);g.dispose();
                }
                for(int i=0;i<panes.size();i++)check(panes.get(i).contentRevision()==before[i],"resize or scrolling parsed HTML");
                perf.put(skin?"reading":"legacy",Map.of("resizeMedianMs",median(resize),"resizeP95Ms",p95(resize),
                    "paintMedianMs",median(paint),"paintP95Ms",p95(paint),"proseDocuments",panes.size()));
            }
            Files.writeString(OUT.resolve("performance.json"),new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(perf));
            System.out.println(perf);
            Path fixture=OUT.resolve("close-fixture.pdf");
            try(var pdf=new org.apache.pdfbox.pdmodel.PDDocument()) {
                pdf.addPage(new org.apache.pdfbox.pdmodel.PDPage());pdf.save(fixture.toFile());
            }
            PdfSource source=PdfSource.open(fixture,OUT.resolve("close-fixture-library"));
            set(workspace,"source",source);
            workspace.releasePdfIfMatches(source.id).get(5,java.util.concurrent.TimeUnit.SECONDS);
            check(flow.getComponentCount()==1 && text(flow).contains("PDF를 불러와 주세요."),"closing PDF left old summary fragments visible");
            check(((Map<?,?>)get(workspace,"summaryProsePanes")).isEmpty()
                && ((Map<?,?>)get(workspace,"summaryMathPanes")).isEmpty()
                && ((Map<?,?>)get(workspace,"summaryFormulaGroups")).isEmpty(),"closing PDF retained its fragment caches");
        } finally {workspace.close();}
    }
    private static void easyHeaderActions()throws Exception {
        StudyHtmlPane pane=new StudyHtmlPane(true);pane.setReadingSkin(true);pane.setEditable(false);
        JPanel root=new JPanel(null);root.setSize(600,600);root.add(pane);
        StudySelectionActions actions=new StudySelectionActions(root,s->{},()->true,s->{});
        java.util.concurrent.atomic.AtomicInteger activated=new java.util.concurrent.atomic.AtomicInteger();
        pane.addHyperlinkListener(e->{if(e.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED){
            check("easy:fixture".equals(e.getDescription()),"wrong easy header target");activated.incrementAndGet();}});
        try {
            pane.setText(SummarySkin.document("","<div class='study-easy'>"+SummarySkin.easyHeader("fixture",false)+"</div><p>다음 본문이에요.</p>",16));
            pane.setSize(600,Short.MAX_VALUE);pane.modelToView2D(pane.getDocument().getLength());pane.setSize(600,pane.getPreferredSize().height);
            pane.modelToView2D(pane.getDocument().getLength());actions.refresh();
            Insets insets=pane.getInsets();Rectangle card=easyCardBounds(pane.getUI().getRootView(pane),
                new Rectangle(insets.left,insets.top,pane.getWidth()-insets.left-insets.right,pane.getHeight()-insets.top-insets.bottom));
            check(card!=null&&card.height>=24,"whole header hit region missing");
            int top=card.y,bottom=card.y+card.height-1;
            snapshot(pane,OUT.resolve("easy-header-hitbox.png"),600,pane.getHeight());
            for(Point point:List.of(new Point(card.x+2,(top+bottom)/2),new Point(300,top+1),new Point(card.x+card.width-3,bottom-1))) {
                check("easy:fixture".equals(SummarySkin.easyActionAt(pane,point)),"header padding not clickable: "+point);
                int before=activated.get();click(pane,point);check(activated.get()==before+1,"header click did not activate exactly once");
            }
            String plain=pane.getDocument().getText(0,pane.getDocument().getLength());
            Rectangle label=pane.modelToView2D(plain.indexOf("쉬운 설명")).getBounds();
            int before=activated.get();click(pane,new Point(label.x+2,label.y+label.height/2));
            check(activated.get()==before+1,"native text link toggled header twice");
            Point start=new Point(300,(top+bottom)/2),end=new Point(340,(top+bottom)/2);
            mouse(pane,java.awt.event.MouseEvent.MOUSE_PRESSED,start,java.awt.event.InputEvent.BUTTON1_DOWN_MASK,java.awt.event.MouseEvent.BUTTON1);
            mouse(pane,java.awt.event.MouseEvent.MOUSE_DRAGGED,end,java.awt.event.InputEvent.BUTTON1_DOWN_MASK,java.awt.event.MouseEvent.NOBUTTON);
            mouse(pane,java.awt.event.MouseEvent.MOUSE_RELEASED,end,0,java.awt.event.MouseEvent.BUTTON1);
            mouse(pane,java.awt.event.MouseEvent.MOUSE_CLICKED,end,0,java.awt.event.MouseEvent.BUTTON1);
            check(activated.get()==before+1,"dragging a header activated its toggle");
            snapshot(pane,OUT.resolve("easy-header-hitbox.png"),600,pane.getHeight());
            pane.setText(SummarySkin.document("","<div class='study-easy'>"+SummarySkin.easyHeader("fixture",true)
                +"<div class='study-easy-body'><p>펼쳐진 설명 본문이에요.</p></div></div>",16));
            pane.setSize(600,Short.MAX_VALUE);pane.modelToView2D(pane.getDocument().getLength());pane.setSize(600,pane.getPreferredSize().height);
            plain=pane.getDocument().getText(0,pane.getDocument().getLength());
            Rectangle body=pane.modelToView2D(plain.indexOf("펼쳐진")).getBounds();Point bodyPoint=new Point(body.x+2,body.y+body.height/2);
            check(SummarySkin.easyActionAt(pane,bodyPoint)==null,"expanded explanation body became a button");
            before=activated.get();click(pane,bodyPoint);check(activated.get()==before,"reading the body collapsed it");
        } finally {actions.close();}
    }
    private static void click(StudyHtmlPane pane,Point point) {
        mouse(pane,java.awt.event.MouseEvent.MOUSE_PRESSED,point,java.awt.event.InputEvent.BUTTON1_DOWN_MASK,java.awt.event.MouseEvent.BUTTON1);
        mouse(pane,java.awt.event.MouseEvent.MOUSE_RELEASED,point,0,java.awt.event.MouseEvent.BUTTON1);
        mouse(pane,java.awt.event.MouseEvent.MOUSE_CLICKED,point,0,java.awt.event.MouseEvent.BUTTON1);
    }
    private static void mouse(StudyHtmlPane pane,int id,Point p,int modifiers,int button){pane.dispatchEvent(new java.awt.event.MouseEvent(pane,id,System.currentTimeMillis(),modifiers,p.x,p.y,0,0,1,false,button));}
    private static Rectangle easyCardBounds(View view,Shape allocation) {
        if(allocation==null)return null;
        if(view.getClass().getSimpleName().equals("CardView")){Rectangle b=allocation.getBounds();return new Rectangle(b.x,b.y+8,b.width-1,b.height-16);}
        for(int i=0;i<view.getViewCount();i++){Rectangle found=easyCardBounds(view.getView(i),view.getChildAllocation(i,allocation));if(found!=null)return found;}
        return null;
    }
    private static double median(List<Double> xs){List<Double> c=new ArrayList<>(xs);Collections.sort(c);return c.get(c.size()/2);}
    private static double p95(List<Double> xs){List<Double> c=new ArrayList<>(xs);Collections.sort(c);return c.get((int)Math.ceil(c.size()*.95)-1);}
    private static void layout(JScrollPane scroll,JPanel flow,int width) {
        scroll.getViewport().setExtentSize(new Dimension(width,700));scroll.getViewport().setSize(width,700);
        flow.setSize(width,Math.max(1,flow.getPreferredSize().height));flow.doLayout();layoutNative(flow);
    }
    private static void layoutNative(Container parent) {
        for(Component child:parent.getComponents())if(child instanceof Container nested && !(child instanceof JEditorPane)) {
            nested.doLayout();layoutNative(nested);
        }
    }
    private static List<StudyHtmlPane> prose(Container parent) {
        List<StudyHtmlPane> result=new ArrayList<>();
        for(Component c:parent.getComponents())if(c instanceof StudyHtmlPane p)result.add(p);
        return result;
    }
    private static String text(Container parent)throws Exception {
        StringBuilder out=new StringBuilder();for(Component c:parent.getComponents())
            if(c instanceof JEditorPane pane)out.append(pane.getDocument().getText(0,pane.getDocument().getLength()));
            else if(c instanceof Container nested)out.append(text(nested));return out.toString();
    }
    private static void views(View view,Map<String,Integer> result) {
        result.merge(view.getClass().getSimpleName(),1,Integer::sum);
        for(int i=0;i<view.getViewCount();i++)views(view.getView(i),result);
    }
    private static Element find(Element element,HTML.Tag tag) {
        if(element.getAttributes().getAttribute(StyleConstants.NameAttribute)==tag)return element;
        for(int i=0;i<element.getElementCount();i++) {
            Element found=find(element.getElement(i),tag);if(found!=null)return found;
        }
        return null;
    }
    private static void snapshot(JComponent component,Path path,int width,int height)throws Exception {
        BufferedImage image=new BufferedImage(width,height,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();
        g.setColor(Color.WHITE);g.fillRect(0,0,width,height);component.paint(g);g.dispose();ImageIO.write(image,"png",path.toFile());
    }
    private static Object get(Object target,String name)throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static void set(Object target,String name,Object value)throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
