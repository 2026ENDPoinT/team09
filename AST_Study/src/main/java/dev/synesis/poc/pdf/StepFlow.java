package dev.synesis.poc.pdf;
import dev.synesis.poc.UiFonts;
import dev.synesis.poc.ui.StudyTheme;

import com.google.gson.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.awt.event.*;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.function.IntConsumer;
import java.util.regex.Pattern;

/** Trusted native renderer for the supplied A (segments) and D (underline) designs. */
final class StepFlow {
    static final String ID = "synesis.step-flow";
    static final String POLICY_VERSION = "ordered-process-v2";
    private static final Pattern LEADING_MARKUP=Pattern.compile("^[#*_`>]+\\s*");
    private static final Pattern CIRCLED_PREFIX=Pattern.compile("(?U)^\\s*[①-⑳⑴-⒇]\\s*");
    private static final Pattern NUMBER_PREFIX=Pattern.compile("(?iu)^\\s*(?:(?:step|stage|phase|단계)\\s*\\d+\\s*[:.)\\-–—]?\\s*|\\d+\\s*단계\\s*[:.)\\-–—]?\\s*|(?:\\(\\d+\\)|\\[\\d+\\]|\\d+\\))\\s*|\\d+[.．:：]\\s+)");
    private static final Pattern INSIGNIFICANT=Pattern.compile("[\\p{P}\\p{Z}\\s]+");
    private static final Pattern WHITESPACE=Pattern.compile("[\\p{Z}\\s]+");
    record Step(String title, String body, String context, String insight, List<Integer> pages) {}
    record Model(String title, String variant, List<Step> steps) {}
    private StepFlow() {}

    static Model resolve(JsonObject block, JsonObject index) {
        try {
            if(block==null || index==null || !block.has("stepFlow") || !block.get("stepFlow").isJsonObject())return null;
            JsonObject value=block.getAsJsonObject("stepFlow");
            if(!ID.equals(text(value,"moduleId")) || value.get("schemaVersion").getAsInt()!=1)return null;
            String variant=text(value,"variant"),title=text(value,"title");
            if(!List.of("a","d").contains(variant) || title.isBlank())return null;
            JsonArray supplied=value.getAsJsonArray("steps");
            if(supplied.size()<3 || !eligible(value,supplied.size()))return null;
            List<Step> steps=new ArrayList<>();
            Set<String> names=new HashSet<>(),bodies=new HashSet<>();
            for(JsonElement item:supplied) {
                JsonObject step=item.getAsJsonObject();
                String name=text(step,"title"),body=text(step,"body");
                if(name.isBlank() || body.isBlank())return null;
                String normalizedName=duplicateKey(name),normalizedBody=duplicateBodyKey(body);
                if(normalizedName.isBlank() || normalizedBody.isBlank()
                        || !names.add(normalizedName) || !bodies.add(normalizedBody))return null;
                List<Integer> pages=new ArrayList<>();
                for(JsonElement citation:step.getAsJsonArray("evidence")) {
                    JsonObject evidence=citation.getAsJsonObject();
                    int page=evidencePage(evidence,index);
                    if(page==0 || text(evidence,"quote").isBlank() && !visualEvidence(evidence))return null;
                    if(!pages.contains(page))pages.add(page);
                }
                if(pages.isEmpty())return null;
                steps.add(new Step(name,body,text(step,"context"),text(step,"insight"),List.copyOf(pages)));
            }
            return new Model(title,variant,List.copyOf(steps));
        } catch(RuntimeException invalid) {return null;}
    }

    private static boolean eligible(JsonObject value,int count) {
        if(!value.has("eligibility") || !value.get("eligibility").isJsonObject())return false;
        JsonObject stamp=value.getAsJsonObject("eligibility");
        JsonElement grounded=stamp.get("sourceGrounded"),transitions=stamp.get("transitionCount");
        return POLICY_VERSION.equals(text(stamp,"policyVersion"))
            && List.of("process","procedure","derivation","cycle").contains(text(stamp,"kind"))
            && grounded!=null && grounded.isJsonPrimitive() && grounded.getAsJsonPrimitive().isBoolean()
            && grounded.getAsBoolean() && transitions!=null && transitions.isJsonPrimitive()
            && transitions.getAsJsonPrimitive().isNumber()
            && transitions.getAsBigDecimal().intValueExact()==count-1;
    }

    private static String duplicateKey(String value) {
        String normalized=LEADING_MARKUP.matcher(value.strip()).replaceFirst("");
        normalized=CIRCLED_PREFIX.matcher(normalized).replaceFirst("");
        normalized=Normalizer.normalize(normalized,Normalizer.Form.NFKC).strip();
        normalized=NUMBER_PREFIX.matcher(normalized).replaceFirst("");
        return INSIGNIFICANT.matcher(normalized).replaceAll("").toLowerCase(Locale.ROOT);
    }

    private static String duplicateBodyKey(String value) {
        String normalized=stripEmphasis(value.strip());
        normalized=CIRCLED_PREFIX.matcher(normalized).replaceFirst("");
        normalized=Normalizer.normalize(normalized,Normalizer.Form.NFKC).strip();
        normalized=NUMBER_PREFIX.matcher(normalized).replaceFirst("");
        normalized=stripEmphasis(normalized);
        // A sign, operator, identifier's case or code punctuation can change
        // the taught result. Only presentation whitespace is insignificant.
        return WHITESPACE.matcher(normalized).replaceAll("");
    }

    private static String stripEmphasis(String value) {
        for(String marker:List.of("**","__","*","_")) {
            if(value.length()>2*marker.length() && value.startsWith(marker) && value.endsWith(marker))
                return value.substring(marker.length(),value.length()-marker.length()).strip();
        }
        return value;
    }

    private static int evidencePage(JsonObject evidence,JsonObject index) {
        try {
            JsonElement value=evidence.get("page");
            if(value==null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber())return 0;
            int page=value.getAsBigDecimal().intValueExact();
            return page>=1 && index!=null && index.has("pages") && index.get("pages").isJsonArray()
                && page<=index.getAsJsonArray("pages").size()?page:0;
        } catch(RuntimeException invalid) {return 0;}
    }

    private static boolean visualEvidence(JsonObject evidence) {
        if(!"visual".equals(text(evidence,"sourceMode")) || !"region_image".equals(text(evidence,"source"))
                || !evidence.has("bbox") || !evidence.get("bbox").isJsonArray())return false;
        JsonArray box=evidence.getAsJsonArray("bbox");
        if(box.size()!=4)return false;
        double[] coordinates=new double[4];
        for(int i=0;i<4;i++) {
            JsonElement value=box.get(i);
            if(!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber())return false;
            coordinates[i]=value.getAsDouble();
            if(!Double.isFinite(coordinates[i]))return false;
        }
        return 0<=coordinates[0] && coordinates[0]<coordinates[2] && coordinates[2]<=1
            && 0<=coordinates[1] && coordinates[1]<coordinates[3] && coordinates[3]<=1;
    }

    /** Older or unapproved modules remain readable without an interactive card. */
    static String fallbackHtml(JsonObject block,JsonObject index,int fontSize) {
        if(resolve(block,index)!=null)return "";
        try {
            if(block==null || !block.has("stepFlow") || !block.get("stepFlow").isJsonObject())return "";
            JsonObject flow=block.getAsJsonObject("stepFlow");
            if(!ID.equals(text(flow,"moduleId")) || !flow.has("steps") || !flow.get("steps").isJsonArray())return "";
            StringBuilder items=new StringBuilder();
            for(JsonElement item:flow.getAsJsonArray("steps")) {
                if(!item.isJsonObject())continue;
                JsonObject step=item.getAsJsonObject();
                String name=text(step,"title"),body=text(step,"body"),context=text(step,"context"),insight=text(step,"insight");
                if(name.isBlank() && body.isBlank() && context.isBlank() && insight.isBlank())continue;
                items.append("<li>");
                if(!name.isBlank())items.append("<p><strong>").append(PdfWorkspace.escape(name)).append("</strong></p>");
                if(!context.isBlank())items.append(StudyMarkdown.render(context,fontSize));
                items.append(StudyMarkdown.render(body,fontSize));
                if(!insight.isBlank())items.append(StudyMarkdown.render(insight,fontSize));
                if(step.has("evidence") && step.get("evidence").isJsonArray()) {
                    for(JsonElement citation:step.getAsJsonArray("evidence")) {
                        if(!citation.isJsonObject())continue;
                        JsonObject evidence=citation.getAsJsonObject();
                        String quote=text(evidence,"quote");
                        int page=evidencePage(evidence,index);
                        boolean visual=quote.isBlank() && visualEvidence(evidence) && page>0;
                        if(quote.isBlank() && !visual)continue;
                        items.append("<p class='muted'>").append(visual?"시각 원문 ":"근거 ");
                        if(page>0)items.append("<a href='page:").append(page).append("'>p.").append(page).append("</a>")
                            .append(quote.isBlank()?"":" · ");
                        items.append(PdfWorkspace.escape(quote)).append("</p>");
                    }
                }
                items.append("</li>");
            }
            if(items.isEmpty())return "";
            String title=text(flow,"title");
            return (title.isBlank()?"":"<p><strong>"+PdfWorkspace.escape(title)+"</strong></p>")
                +"<ul>"+items+"</ul>";
        } catch(RuntimeException invalid) {return "";}
    }
    private static String text(JsonObject value,String key) {
        JsonElement item=value.get(key);
        return item!=null && item.isJsonPrimitive() && item.getAsJsonPrimitive().isString()?item.getAsString():"";
    }

    static final class Panel extends JPanel {
        private final Model model;
        private final int fontSize;
        private final boolean blackText;
        private final IntConsumer changed;
        private final Color accent;
        private final JLabel counter=new JLabel();
        private final JEditorPane detail=new StudyHtmlPane();
        private final List<JButton> tabs=new ArrayList<>();
        private final JButton previous=pagerButton("‹"),next=pagerButton("›");
        private final JPanel header=new JPanel(new BorderLayout(12,0));
        private final JPanel top=new JPanel(new BorderLayout(0,18));
        private final JPanel footer=new JPanel(new BorderLayout(8,0));
        private final JScrollPane navigation;
        private int selected;

        Panel(Model model,int fontSize,int initial,IntConsumer changed,IntConsumer navigate) {
            this(model,fontSize,initial,changed,navigate,false);
        }
        Panel(Model model,int fontSize,int initial,IntConsumer changed,IntConsumer navigate,boolean blackText) {
            super(new BorderLayout(0,20));
            this.model=model;this.fontSize=fontSize;this.changed=changed;this.blackText=blackText;
            accent=model.variant.equals("a")?StudyTheme.ACCENT:new Color(0x242834);
            setOpaque(false);setAlignmentX(Component.LEFT_ALIGNMENT);
            JLabel title=new JLabel("<html>"+PdfWorkspace.escape(model.title)+"</html>");
            title.setFont(new Font(UiFonts.FAMILY,Font.BOLD,Math.max(18,fontSize+3)));
            title.setForeground(blackText?Color.BLACK:new Color(0x202632));
            header.setOpaque(false);header.add(title,BorderLayout.CENTER);header.add(counter,BorderLayout.EAST);
            counter.setForeground(accent);counter.setFont(new Font(UiFonts.FAMILY,Font.PLAIN,13));
            top.setOpaque(false);top.add(header,BorderLayout.NORTH);
            TabStrip strip=new TabStrip(model.variant.equals("a"));
            for(int i=0;i<model.steps.size();i++) {
                final int number=i;
                JButton tab=new JButton(){
                    @Override protected void paintComponent(Graphics g) {
                        Graphics2D canvas=(Graphics2D)g.create();
                        canvas.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                        if(selected==number) {
                            canvas.setColor(Color.WHITE);
                            if(Panel.this.model.variant.equals("a"))canvas.fillRoundRect(3,3,getWidth()-6,getHeight()-6,16,16);
                            else {canvas.setColor(accent);canvas.fillRoundRect(12,getHeight()-3,getWidth()-24,2,2,2);}
                        }
                        canvas.dispose();super.paintComponent(g);
                    }
                };
                String titleText=model.steps.get(i).title;
                List<String> lines=tabLines(titleText);
                tab.setText("<html><center><span style='font-size:10px'>"+String.format("%02d",i+1)+
                    "</span><br>"+PdfWorkspace.escape(lines.get(0))+
                    (lines.size()>1?"<br>"+PdfWorkspace.escape(lines.get(1)):"")+"</center></html>");
                tab.setFont(new Font(UiFonts.FAMILY,Font.PLAIN,Math.min(18,Math.max(12,fontSize-4))));
                FontMetrics metrics=tab.getFontMetrics(tab.getFont());
                int labelWidth=lines.stream().mapToInt(metrics::stringWidth).max().orElse(0);
                int tabWidth=Math.max(112,Math.min(240,labelWidth+24));
                tab.setPreferredSize(new Dimension(tabWidth,82));
                tab.setMaximumSize(new Dimension(tabWidth,82));
                tab.setBorder(new EmptyBorder(7,5,7,5));
                tab.setContentAreaFilled(false);tab.setToolTipText(model.steps.get(i).title);
                tab.getAccessibleContext().setAccessibleName((i+1)+"단계 "+model.steps.get(i).title);
                tab.addActionListener(e->select(number));
                bind(tab,"RIGHT",()->selectAndFocus((selected+1)%tabs.size()));
                bind(tab,"LEFT",()->selectAndFocus((selected+tabs.size()-1)%tabs.size()));
                bind(tab,"HOME",()->selectAndFocus(0));bind(tab,"END",()->selectAndFocus(tabs.size()-1));
                tabs.add(tab);
                if(i>0)strip.add(Box.createHorizontalStrut(2));
                strip.add(tab);
            }
            navigation=new dev.synesis.poc.ui.FadeScrollPane(strip,JScrollPane.VERTICAL_SCROLLBAR_NEVER,JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED) {
                @Override protected void processMouseWheelEvent(MouseWheelEvent event) {
                    if(event.isShiftDown()) {super.processMouseWheelEvent(event);return;}
                    JScrollPane outer=(JScrollPane)SwingUtilities.getAncestorOfClass(JScrollPane.class,Panel.this);
                    if(outer==null) {super.processMouseWheelEvent(event);return;}
                    Point point=SwingUtilities.convertPoint(this,event.getPoint(),outer);
                    outer.dispatchEvent(new MouseWheelEvent(outer,event.getID(),event.getWhen(),event.getModifiersEx(),
                        point.x,point.y,event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),
                        event.isPopupTrigger(),event.getScrollType(),event.getScrollAmount(),
                        event.getWheelRotation(),event.getPreciseWheelRotation()));
                    event.consume();
                }
            };
            navigation.setBorder(BorderFactory.createEmptyBorder());navigation.setOpaque(false);
            navigation.getViewport().setOpaque(false);navigation.setPreferredSize(new Dimension(400,100));
            navigation.addComponentListener(new ComponentAdapter(){
                @Override public void componentResized(ComponentEvent e){SwingUtilities.invokeLater(()->revealSelected());}
            });
            top.add(navigation,BorderLayout.CENTER);add(top,BorderLayout.NORTH);
            detail.setEditable(false);detail.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES,true);
            detail.setBackground(new Color(model.variant.equals("a")?0xf7f9fc:0xffffff));
            detail.setBorder(new EmptyBorder(14,model.variant.equals("a")?18:2,12,model.variant.equals("a")?18:2));
            detail.addHyperlinkListener(e->{
                if(e.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED && e.getDescription().startsWith("page:"))
                    try{navigate.accept(Integer.parseInt(e.getDescription().substring(5)));}catch(NumberFormatException ignored){}
            });
            add(detail,BorderLayout.CENTER);
            footer.setOpaque(false);
            JLabel hint=new JLabel("단계를 눌러 설명을 확인하세요");hint.setForeground(new Color(0x828996));
            hint.setFont(new Font(UiFonts.FAMILY,Font.PLAIN,12));footer.add(hint,BorderLayout.CENTER);
            JPanel pager=new JPanel(new FlowLayout(FlowLayout.RIGHT,5,0));pager.setOpaque(false);
            previous.getAccessibleContext().setAccessibleName("이전 단계");next.getAccessibleContext().setAccessibleName("다음 단계");
            for(JButton button:List.of(previous,next)) {button.setPreferredSize(new Dimension(34,30));button.setMargin(new Insets(0,0,0,0));pager.add(button);}
            previous.addActionListener(e->select(selected-1));next.addActionListener(e->select(selected+1));
            footer.add(pager,BorderLayout.EAST);add(footer,BorderLayout.SOUTH);
            select(initial);
        }
        private static void bind(JComponent component,String key,Runnable action) {
            component.getInputMap().put(KeyStroke.getKeyStroke(key),key);
            component.getActionMap().put(key,new AbstractAction(){public void actionPerformed(ActionEvent event){action.run();}});
        }
        private void selectAndFocus(int number){select(number);tabs.get(selected).requestFocusInWindow();}
        private void revealSelected(){tabs.get(selected).scrollRectToVisible(new Rectangle(0,0,tabs.get(selected).getWidth(),tabs.get(selected).getHeight()));}
        private static List<String> tabLines(String title) {
            String clean=title.strip().replaceAll("\\s+"," ");
            int length=clean.codePointCount(0,clean.length());
            if(length<=15)return List.of(clean);
            int split=clean.offsetByCodePoints(0,15);
            int space=clean.lastIndexOf(' ',split);
            if(space>=8)split=space;
            String first=clean.substring(0,split).strip();
            String rest=clean.substring(split).strip();
            int restLength=rest.codePointCount(0,rest.length());
            if(restLength>15)rest=rest.substring(0,rest.offsetByCodePoints(0,14)).stripTrailing()+"…";
            return List.of(first,rest);
        }
        void select(int number) {
            selected=Math.max(0,Math.min(model.steps.size()-1,number));
            Step step=model.steps.get(selected);
            for(int i=0;i<tabs.size();i++) {
                tabs.get(i).setForeground(i==selected?accent:new Color(0x727c8e));
                tabs.get(i).getAccessibleContext().setAccessibleDescription(i==selected?"선택한 단계":"단계 선택");
                tabs.get(i).repaint();
            }
            counter.setText(String.format("%02d / %02d",selected+1,tabs.size()));
            previous.setEnabled(selected>0);next.setEnabled(selected<tabs.size()-1);
            StringBuilder html=new StringBuilder("<html><head><style>body{font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic';font-size:")
                .append(fontSize).append("pt;color:#596474;margin:0;}p{margin-top:4px;margin-bottom:10px;}h2{color:#202632;font-size:")
                .append(fontSize+6).append("pt;margin:8px 0 12px;}a{color:#76243d;}pre{background:#eef0f3;}</style></head><body>")
                .append("<span style='font-size:10pt;color:#828996'>STEP ").append(String.format("%02d",selected+1))
                .append(step.context.isBlank()?"":" · "+PdfWorkspace.escape(step.context)).append("</span><h2>")
                .append(PdfWorkspace.escape(step.title)).append("</h2>").append(StudyMarkdown.render(step.body,fontSize));
            if(!step.insight.isBlank())html.append("<hr>").append(StudyMarkdown.render(step.insight,fontSize));
            html.append("<p style='font-size:11pt'>근거 ");
            for(int page:step.pages)html.append("<a href='page:").append(page).append("'>p.").append(page).append("</a> &nbsp; ");
            String document=html.append("</p></body></html>").toString();
            detail.setText(blackText?SummarySkin.blackTextDocument(document):document);
            detail.setCaretPosition(0);changed.accept(selected);revalidate();repaint();
            revealSelected();
        }
        int selected(){return selected;}
        @Override public Insets getInsets() {
            int side=Math.max(26,(int)Math.round(getWidth()*0.075)+26);
            return new Insets(26,side,22,side);
        }
        @Override public Dimension getPreferredSize() {
            int width=getWidth()>0?getWidth():640;
            int innerWidth=Math.max(100,width-getInsets().left-getInsets().right);
            detail.setSize(innerWidth,Math.max(1,detail.getPreferredSize().height));
            header.setSize(innerWidth,10000);
            return new Dimension(width,44+Math.max(38,header.getPreferredSize().height)+18+100+40+
                Math.max(180,detail.getPreferredSize().height)+footer.getPreferredSize().height);
        }
        @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        @Override protected void paintComponent(Graphics g) {
            Graphics2D canvas=(Graphics2D)g.create();
            canvas.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            int x=Math.max(0,(int)Math.round(getWidth()*0.075));
            int w=Math.max(1,getWidth()-2*x-12),h=Math.max(1,getHeight()-14);
            for(int i=8;i>=1;i--) {
                canvas.setColor(new Color(31,48,76,Math.max(1,11-i)));
                canvas.fillRoundRect(x+6-i,6-i,w+2*i,h+2*i,28+2*i,28+2*i);
            }
            canvas.setColor(model.variant.equals("a")?StudyTheme.ACCENT_SOFT:new Color(0xf4f5f8));
            canvas.fillRoundRect(x+6,6,w,h,28,28);
            canvas.setColor(new Color(model.variant.equals("a")?0xe2beca:0xdce1e9));
            canvas.drawRoundRect(x+6,6,w,h,28,28);
            canvas.dispose();
        }
    }
    private static JButton pagerButton(String text) {
        JButton button=new JButton(text){
            @Override protected void paintComponent(Graphics g){
                Graphics2D canvas=(Graphics2D)g.create();
                canvas.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                canvas.setColor(getModel().isRollover()?StudyTheme.ACCENT_SOFT:new Color(0xf5f6f8));
                canvas.fillOval(2,1,getWidth()-4,getHeight()-2);canvas.dispose();super.paintComponent(g);
            }
        };
        button.setContentAreaFilled(false);button.setBorder(BorderFactory.createEmptyBorder());
        button.setFont(new Font("Dialog",Font.PLAIN,20));button.setForeground(new Color(0x828996));
        return button;
    }
    private static final class TabStrip extends JPanel implements Scrollable {
        private final boolean segments;
        TabStrip(boolean segments){this.segments=segments;setLayout(new BoxLayout(this,BoxLayout.X_AXIS));setOpaque(false);}
        @Override protected void paintComponent(Graphics g){
            if(segments){Graphics2D canvas=(Graphics2D)g.create();
                canvas.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                canvas.setColor(new Color(0xf1f2f5));canvas.fillRoundRect(0,0,getWidth(),getHeight(),20,20);canvas.dispose();}
            super.paintComponent(g);
        }
        public Dimension getPreferredScrollableViewportSize(){return new Dimension(400,82);}
        public int getScrollableUnitIncrement(Rectangle r,int o,int d){return 100;}
        public int getScrollableBlockIncrement(Rectangle r,int o,int d){return Math.max(100,r.width-100);}
        public boolean getScrollableTracksViewportHeight(){return true;}
        public boolean getScrollableTracksViewportWidth(){return getParent()!=null && getPreferredSize().width<=getParent().getWidth();}
    }
}
