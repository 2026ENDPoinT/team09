package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import java.awt.*;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.swing.text.*;
import javax.swing.text.html.*;
import javax.swing.SizeRequirements;

/** Presentation only: the stored Markdown, evidence, generation schema and prompts stay intact. */
final class SummarySkin {
    static final Color SOFT = MistWorkspaceTheme.SOFT, LINE = MistWorkspaceTheme.INNER_LINE;
    private static final Pattern DISPLAY_MATH = Pattern.compile(
        "(?s)(?:<span[^>]*>)?<math\\b(?=[^>]*display='block')(?![^>]*data-study-card)[^>]*>.*?</math>(?:</span>)?");
    private static final Pattern PARAGRAPH=Pattern.compile("(?s)(<p(?:\\s[^>]*)?>)(.*?)</p>");
    private static final Pattern QUOTE = Pattern.compile("(?s)<blockquote>(.*?)</blockquote>");
    private static final String TABLE = "<table border='1' cellspacing='0' cellpadding='7' width='100%'>";
    private static final Pattern DATA_TABLE=Pattern.compile(Pattern.quote(TABLE)+"(.*?)</table>",Pattern.DOTALL);
    private static final Pattern QUOTE_TAG=Pattern.compile("</?blockquote>");
    private static final Pattern SCROLL_MATH=Pattern.compile("(?:<br>\\s*)?<!--MATHSCROLL:([A-Za-z0-9]+)-->(?:\\s*<br>)?");
    private static final String TAIL="(?:[,.，]|(?:이에요|예요|입니다|이 돼요|가 돼요|이 성립해요|가 성립해요|을 얻어요|를 얻어요|으로 나타내요|로 나타내요)\\.|(?:을|를|에)\\s*대입하면)";
    private static final Pattern SENTENCE_TAIL=Pattern.compile(
        "^(?:\\s|<br>)*"+TAIL+"(?=\\s|<br>|</p>|$)");
    record FormulaGroup(String body,boolean emphasized) {}
    record FormulaPresentation(String body,Map<String,FormulaGroup> groups) {}

    /** Lift explicit mathematical quotes as whole groups before wide-math marker splitting. */
    static FormulaPresentation prepare(String body) {
        body=joinEquationTails(body);
        Map<String,FormulaGroup> groups=new LinkedHashMap<>();
        Matcher tags=QUOTE_TAG.matcher(body);StringBuilder result=new StringBuilder();
        int depth=0,open=-1,content=-1,cursor=0;
        while(tags.find()) {
            if(tags.group().equals("<blockquote>")) {
                if(depth++==0) {open=tags.start();content=tags.end();}
            } else if(depth>0 && --depth==0) {
                String inside=body.substring(content,tags.start());
                if(inside.contains("<math ") || inside.contains("<!--MATHSCROLL:")) {
                    // Restore wide vectors inside the quote so its related formulas remain
                    // in one horizontal viewport, instead of splitting the quote into panes.
                    Matcher math=SCROLL_MATH.matcher(inside);StringBuffer restored=new StringBuffer();
                    boolean complete=true;
                    while(math.find()) {
                        StudyMarkdown.ScrollableMath equation=StudyMarkdown.scrollableMath(math.group(1));
                        if(equation==null) {complete=false;break;}
                        String html=equation.html().replace("display='inline'","display='block'");
                        math.appendReplacement(restored,Matcher.quoteReplacement(html));
                    }
                    if(complete) {
                        math.appendTail(restored);
                        String key=Integer.toString(groups.size());groups.put(key,new FormulaGroup(restored.toString(),true));
                        result.append(body,cursor,open).append("<!--FORMULAGROUP:").append(key).append("-->");
                        cursor=tags.end();
                    }
                }
            }
        }
        String quoted=result.append(body,cursor,body.length()).toString();
        // A saved inline equation may also be a wide scroll row. Keep a small
        // sentence ending inside that neutral row, across the native pane boundary.
        Matcher wide=SCROLL_MATH.matcher(quoted);result=new StringBuilder();cursor=0;
        while(wide.find()) {
            if(wide.start()<cursor)continue;
            StudyMarkdown.ScrollableMath equation=StudyMarkdown.scrollableMath(wide.group(1));
            if(equation==null)continue;
            int end=wide.end();String ending="";
            Matcher tail=SENTENCE_TAIL.matcher(quoted).region(end,quoted.length());
            if(tail.find()) {ending=continuation(tail.group());end=tail.end();}
            String key=Integer.toString(groups.size());
            groups.put(key,new FormulaGroup("<p align='center'>"+equation.html()+ending+"</p>",false));
            result.append(quoted,cursor,wide.start()).append("<!--FORMULAGROUP:").append(key).append("-->");cursor=end;
        }
        return new FormulaPresentation(result.append(quoted,cursor,quoted.length()).toString(),groups);
    }

    private SummarySkin() {}

    private static String continuation(String tail) {
        return " <span style='white-space:nowrap'>"+tail.replace("<br>","").strip()+"</span>";
    }

    private static String joinEquationTails(String body) {
        // A blank line in generated Markdown is not necessarily a sentence
        // boundary: attach only recognised continuation phrases after math.
        Pattern detached=Pattern.compile("(</math>(?:</span>)?|<!--MATHSCROLL:[A-Za-z0-9]+-->(?:<br>)?)"
            +"\\s*</p>\\s*<p>("+TAIL+")(?=\\s|<br>|</p>|$)(\\s*</p>)?");
        Matcher matcher=detached.matcher(body);StringBuffer result=new StringBuffer();
        while(matcher.find())matcher.appendReplacement(result,Matcher.quoteReplacement(
            matcher.group(1)+" "+matcher.group(2)+(matcher.group(3)==null?"":"</p>")));
        matcher.appendTail(result);return result.toString();
    }

    /** Opt in only lecture-explanation documents, including their formula panes. */
    static String blackTextDocument(String document) {
        return document.replace("<body>","<body data-synesis-black-text='true'>");
    }

    static String decorate(String body) {
        // Empty source/navigation anchors between block tags otherwise create an
        // implied blank paragraph in Swing. Keep them inside the next text block.
        body=body.replaceAll("((?:<a name='[^']+'></a>\\s*)+)(<(?:p|h[1-6])(?:\\s[^>]*)?>)","$2$1");
        body=body.replaceAll("(</h[1-4]>\\s*)<p>","$1<p style='margin-top:0;'>");
        // Only modify renderer-owned tags; escaped user HTML and code remain literal text.
        Matcher tables=DATA_TABLE.matcher(body);StringBuffer styledTables=new StringBuffer();
        while(tables.find()) {
            String cells=tables.group(1).replaceAll("<(td|th)(?=[ >])",
                "<$1 style='border-bottom-width:1px;border-bottom-style:solid;border-bottom-color:#dfe9f7;'");
            tables.appendReplacement(styledTables,Matcher.quoteReplacement(
                "<table class='study-table' border='0' cellspacing='0' cellpadding='10' width='100%'>"+cells+"</table>"));
        }
        tables.appendTail(styledTables);body=styledTables.toString();
        body = body.replaceAll("<ol(?=[ >])", "<ol class='study-steps'");
        Matcher quotes = QUOTE.matcher(highlightEquations(body));
        StringBuffer result = new StringBuffer();
        while(quotes.find()) {
            String inside=quotes.group(1);
            boolean shortQuote=inside.replaceAll("<[^>]+>","").strip().length()<=160
                && !inside.matches("(?s).*<(?:blockquote|ol|ul|table|pre)\\b.*")
                && inside.indexOf("<p>")==inside.lastIndexOf("<p>");
            quotes.appendReplacement(result,Matcher.quoteReplacement("<blockquote class='"
                +(shortQuote?"study-highlight":"study-quote")+"'>"+inside+"</blockquote>"));
        }
        quotes.appendTail(result);
        return result.toString();
    }

    private static String equationBlock(String equation,String tail) {
        return "<div class='study-equation'><p align='center'>"
            +equation.replace("<math ","<math data-study-card='1' ")+tail+"</p></div>";
    }
    private static String highlightEquations(String body) {
        body=joinEquationTails(body);
        Matcher paragraphs=PARAGRAPH.matcher(body);StringBuffer result=new StringBuffer();
        while(paragraphs.find()) {
            String inside=paragraphs.group(2);Matcher math=DISPLAY_MATH.matcher(inside);
            StringBuilder out=new StringBuilder();int start=0;
            while(math.find()) {
                String before=inside.substring(start,math.start()).replaceAll("(?:<br>\\s*)+$","");
                if(!before.isBlank())out.append(paragraphs.group(1)).append(before).append("</p>");
                start=math.end();
                // Saved prose often leaves '이에요.' or a comma immediately after a block.
                // Keep those exact characters attached to its equation, not alone on a row.
                Matcher tail=SENTENCE_TAIL.matcher(inside.substring(start));String ending="";
                if(tail.find()) {ending=continuation(tail.group());start+=tail.end();}
                out.append(equationBlock(math.group(),ending));
            }
            if(start==0)continue;
            String rest=inside.substring(start).replaceAll("^(?:\\s*<br>)+","");
            if(!rest.isBlank())out.append(paragraphs.group(1)).append(rest).append("</p>");
            paragraphs.appendReplacement(result,Matcher.quoteReplacement(out.toString()));
        }
        paragraphs.appendTail(result);
        // Tight list items can contain a display equation without a surrounding paragraph.
        Matcher remaining=DISPLAY_MATH.matcher(result.toString());StringBuffer complete=new StringBuffer();
        while(remaining.find())remaining.appendReplacement(complete,Matcher.quoteReplacement(equationBlock(remaining.group(),"")));
        remaining.appendTail(complete);
        // The same legacy sentence tail may have its own paragraph after a blank line.
        return complete.toString().replaceAll(
            "</p></div>\\s*<p>((?:이에요|예요|입니다|가 성립해요|를 얻어요|을 얻어요)\\.|[,，])</p>",
            " $1</p></div>");
    }

    static String document(String title,String body,int font) {
        return document(title,body,font,false);
    }
    static String headingSizes(int font) {
        return "h1,h2,h3,h4{font-weight:bold;}h1{font-size:"+Math.round(font*36f/18f*.9f)+"pt;}"
            +"h2{font-size:"+Math.round(font*32f/18f*.9f)+"pt;}"
            +"h3{font-size:"+Math.round(font*26f/18f*.9f)+"pt;}"
            +"h4{font-size:"+Math.round(font*1.1f)+"pt;}"
            +"h5{font-size:"+Math.round(font*20f/18f)+"pt;}"
            +"h6{font-size:"+Math.round(font*20f/18f)+"pt;}";
    }
    static String formulaDocument(String body,int font) {return document("",body,font,true);}
    private static String document(String title,String body,int font,boolean formulaGroup) {
        String card="margin:8px 0;padding:16px;";
        String css="body{font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;"
            +"font-size:"+font+"pt;font-weight:normal;color:#252629;margin-top:"+(title.isEmpty()?0:18)
            +"px;margin-right:"+(formulaGroup?0:24)+"px;margin-bottom:0;margin-left:"+(formulaGroup?0:24)+"px;line-height:1.55;}"
            +"h1{color:#141414;margin:0 0 2px;}"
            +"h2{color:#141414;margin:4px 0 2px;}"
            +"h3{color:#141414;margin:4px 0 2px;}"
            +"h4{color:#141414;margin:4px 0 2px;}"+headingSizes(font)
            +"p{margin:4px 0 14px;}strong,b{color:#182234;}a{color:#252629;text-decoration:none;font-weight:normal;}"
            +"ol{list-style-type:none;margin:10px 0 16px 36px;padding:0;}ul{margin:10px 0 16px 24px;}"
            +"li{margin:0 0 10px;}li p{margin:0 0 8px;}"
            +"table{margin:12px 0 18px;}th{background:"+MistWorkspaceTheme.SOFT_HEX+";color:#182234;font-weight:bold;}"
            +"td,th{padding:10px 12px;border-bottom:1px solid #dfe9f7;vertical-align:top;}"
            +".study-action{margin:0;}.study-action td{padding:0;border:0;vertical-align:middle;}"
            +".study-overview{"+card+"}.study-overview h2{font-size:"+font+"pt;margin:0 0 12px;}"
            +".study-easy{margin:8px 0;padding:10px 12px;}.study-easy-body{margin:14px 0 0;padding:0;}"
            +".study-equation{margin:6px 0;padding:4px 0;}.study-equation p{margin:0;text-align:center;}"
            +"blockquote{margin:8px 0;padding:12px;}.study-highlight{text-align:center;color:#182234;font-weight:bold;}"
            +".study-highlight p{margin:0;text-align:center;}"
            +".study-quote{text-align:left;}"
            +".muted{color:#45474c;font-size:"+Math.max(6,Math.round(font*.82f))+"pt;}"
            +".warning{background:#fff3dc;color:#825b14;padding:10px;}"
            +"code{font-family:monospace;font-size:"+font+"pt;background:"+StudyCodeBlock.INLINE_BACKGROUND+";padding:2px 4px;}"
            +"pre{font-family:monospace;font-size:"+font+"pt;background:"+StudyCodeBlock.BACKGROUND+";padding:12px;margin:12px 0 18px;}pre code{padding:0;background:"+StudyCodeBlock.BACKGROUND+";}";
        return "<html><head><style>"+css+"</style></head><body>"
            +(title.isEmpty()?"":"<h1>"+PdfWorkspace.escape(title)+"</h1>")+decorate(body)+"</body></html>";
    }

    static String easyHeader(String key,boolean open) {
        String href="easy:"+PdfWorkspace.escape(key);
        String spark=SummarySkin.class.getResource("/dev/synesis/poc/mist/summary-spark.png").toExternalForm();
        String arrow=SummarySkin.class.getResource("/dev/synesis/poc/mist/summary-arrow.png").toExternalForm();
        return "<table class='study-action' width='100%' cellspacing='0' cellpadding='0'><tr>"
            +"<td width='24'><a href='"+href+"'><img src='"+spark+"' width='16' height='16' border='0'></a></td>"
            +"<td><a href='"+href+"'>쉬운 설명 "+(open?"접기":"보기")+"</a></td>"
            +"<td width='16' align='right'><a href='"+href+"'><img class='study-easy-arrow' src='"+arrow+"' width='16' height='16' border='0'></a></td>"
            +"</tr></table>";
    }

    static View view(Element element) {
        Object tag=element.getAttributes().getAttribute(StyleConstants.NameAttribute);
        String style=String.valueOf(element.getAttributes().getAttribute(HTML.Attribute.CLASS));
        if(tag==HTML.Tag.DIV && (style.equals("study-overview") || style.equals("study-easy")) || tag==HTML.Tag.BLOCKQUOTE)
            return new CardView(element,style.equals("study-easy"));
        if(tag==HTML.Tag.OL)return new NumberedListView(element);
        if((tag==HTML.Tag.P || tag==HTML.Tag.IMPLIED) && inTable(element))return new TableParagraphView(element);
        if(element.getAttributes().getAttribute(HTML.Tag.A) instanceof AttributeSet link
            && String.valueOf(link.getAttribute(HTML.Attribute.HREF)).startsWith("page:"))
            return new CitationView(element);
        if(tag==HTML.Tag.IMG) {
            ImageView image=style.equals("study-easy-arrow")?new ImageView(element){
                @Override public void paint(Graphics graphics,Shape allocation){
                    Graphics2D g=(Graphics2D)graphics.create();Rectangle box=allocation.getBounds();
                    try{g.rotate(Math.PI/2,box.getCenterX(),box.getCenterY());super.paint(g,allocation);}
                    finally{g.dispose();}
                }
            }:new ImageView(element);
            image.setLoadsSynchronously(true);
            return image;
        }
        return null;
    }

    private static boolean inTable(Element element) {
        for(Element parent=element.getParentElement();parent!=null;parent=parent.getParentElement()) {
            Object tag=parent.getAttributes().getAttribute(StyleConstants.NameAttribute);
            if(tag==HTML.Tag.TD || tag==HTML.Tag.TH)return true;
        }
        return false;
    }
    /** Keep word wrapping, but allow a single oversized token to fit a narrow table cell. */
    private static final class TableParagraphView extends javax.swing.text.html.ParagraphView {
        TableParagraphView(Element element) {super(element);}
        @Override protected SizeRequirements calculateMinorAxisRequirements(int axis,SizeRequirements result) {
            result=super.calculateMinorAxisRequirements(axis,result);
            result.minimum=Math.min(result.minimum,48);
            return result;
        }
    }

    private static final class CardView extends BlockView {
        private final boolean outlined;
        private final String easyAction;
        CardView(Element element,boolean outlined) {super(element,View.Y_AXIS);this.outlined=outlined;easyAction=outlined?easyHref(element):null;}
        String actionAt(Point point,Shape allocation) {
            if(easyAction==null)return null;
            Rectangle box=allocation.getBounds();
            Rectangle hit=new Rectangle(box.x,box.y+8,box.width-1,Math.max(1,box.height-16));
            for(int i=0;i<getViewCount();i++)if("study-easy-body".equals(String.valueOf(getView(i).getElement().getAttributes().getAttribute(HTML.Attribute.CLASS)))) {
                Shape body=getChildAllocation(i,allocation);
                if(body==null)return null;
                // The closed card is all button; only the expanded explanation is excluded.
                hit.height=Math.min(hit.height,Math.max(0,body.getBounds().y-hit.y));break;
            }
            return hit.contains(point)?easyAction:null;
        }
        @Override public void paint(Graphics graphics,Shape allocation) {
            Rectangle box=allocation.getBounds();
            if(graphics.getClipBounds()!=null && !graphics.getClipBounds().intersects(box))return;
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(outlined?Color.WHITE:SOFT);
                g.fillRoundRect(box.x,box.y+8,box.width-1,Math.max(1,box.height-16),16,16);
                g.setColor(outlined?MistWorkspaceTheme.LINE:LINE);
                g.drawRoundRect(box.x,box.y+8,box.width-1,Math.max(1,box.height-16),16,16);
            } finally {g.dispose();}
            super.paint(graphics,allocation);
        }
    }

    private static String easyHref(Element element) {
        if(element.getAttributes().getAttribute(HTML.Tag.A) instanceof AttributeSet link
            && link.getAttribute(HTML.Attribute.HREF) instanceof String href && href.startsWith("easy:"))return href;
        for(int i=0;i<element.getElementCount();i++){String href=easyHref(element.getElement(i));if(href!=null)return href;}
        return null;
    }

    static String easyActionAt(javax.swing.JEditorPane pane,Point point) {
        Insets insets=pane.getInsets();
        return easyActionAt(pane.getUI().getRootView(pane),new Rectangle(insets.left,insets.top,
            pane.getWidth()-insets.left-insets.right,pane.getHeight()-insets.top-insets.bottom),point);
    }
    private static String easyActionAt(View view,Shape allocation,Point point) {
        if(allocation==null || !allocation.getBounds().contains(point))return null;
        if(view instanceof CardView card){String action=card.actionAt(point,allocation);if(action!=null)return action;}
        int index=view.getViewIndex(point.x,point.y,allocation);
        if(index<0 || index>=view.getViewCount())return null;
        return easyActionAt(view.getView(index),view.getChildAllocation(index,allocation),point);
    }

    private static final class NumberedListView extends javax.swing.text.html.ListView {
        private final int first;
        private Font badgeFont;
        NumberedListView(Element element) {
            super(element);
            int start=1;
            try {start=Integer.parseInt(String.valueOf(element.getAttributes().getAttribute(HTML.Attribute.START)));}
            catch(NumberFormatException ignored) {}
            first=start;
        }
        @Override public void paint(Graphics graphics,Shape allocation) {
            super.paint(graphics,allocation);
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                if(badgeFont==null) {
                    Font font=((HTMLDocument)getDocument()).getStyleSheet().getFont(getAttributes());
                    badgeFont=font.deriveFont(Math.min(14f,Math.max(11f,font.getSize2D()*.85f)));
                }
                g.setFont(badgeFont);
                FontMetrics metrics=g.getFontMetrics();
                int size=Math.max(24,metrics.getHeight()+4);
                for(int i=0;i<getViewCount();i++) {
                    Shape child=getChildAllocation(i,allocation);
                    if(child==null || graphics.getClipBounds()!=null && !graphics.getClipBounds().intersects(child.getBounds()))continue;
                    Rectangle row=child.getBounds();
                    String number=Integer.toString(first+i);
                    int width=Math.max(size,metrics.stringWidth(number)+10),x=row.x-width-10,y=row.y;
                    g.setColor(SOFT);g.fillRoundRect(x,y,width,size,10,10);
                    g.setColor(getContainer() instanceof StudyHtmlPane pane&&pane.blackText()?Color.BLACK:new Color(0x252629));
                    g.drawString(number,x+(width-metrics.stringWidth(number))/2,
                        y+(size-metrics.getHeight())/2+metrics.getAscent());
                }
            } finally {g.dispose();}
        }
    }

    /** Keep native link hit testing and selection while giving the short page link padding. */
    private static final class CitationView extends InlineView {
        CitationView(Element element) {super(element);}
        private Shape inner(Shape allocation) {
            Rectangle box=allocation.getBounds();box.x+=5;box.width=Math.max(1,box.width-10);return box;
        }
        @Override public float getPreferredSpan(int axis) {return super.getPreferredSpan(axis)+(axis==X_AXIS?10:0);}
        // FlowView measures TabableView separately when choosing line breaks. Include the
        // same chip padding there, or a row fits on paper but overflows when painted.
        @Override public float getTabbedSpan(float x,TabExpander expander) {
            return super.getTabbedSpan(x+5,expander)+10;
        }
        @Override public float getMinimumSpan(int axis) {return getPreferredSpan(axis);}
        @Override public float getMaximumSpan(int axis) {return getPreferredSpan(axis);}
        @Override public int getBreakWeight(int axis,float pos,float len) {return BadBreakWeight;}
        @Override public View breakView(int axis,int offset,float pos,float len) {return this;}
        @Override public void paint(Graphics graphics,Shape allocation) {
            Rectangle box=allocation.getBounds();Graphics2D g=(Graphics2D)graphics.create();
            try {g.setColor(SOFT);g.fillRoundRect(box.x,box.y,box.width,box.height,8,8);}
            finally {g.dispose();}
            super.paint(graphics,inner(allocation));
        }
        @Override public Shape modelToView(int pos,Shape allocation,Position.Bias bias)throws BadLocationException {
            return super.modelToView(pos,inner(allocation),bias);
        }
        @Override public int viewToModel(float x,float y,Shape allocation,Position.Bias[] bias) {
            return super.viewToModel(x,y,inner(allocation),bias);
        }
    }
}
