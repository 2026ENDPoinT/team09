package dev.synesis.poc.pdf;

import org.commonmark.node.Code;
import org.commonmark.node.Node;
import org.commonmark.node.Paragraph;
import org.commonmark.node.SourceSpan;
import org.commonmark.parser.IncludeSourceSpans;
import org.commonmark.parser.Parser;
import org.commonmark.ext.gfm.tables.TablesExtension;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.text.SimpleAttributeSet;
import javax.swing.text.StyleConstants;
import javax.swing.text.StyledDocument;
import java.awt.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Quiz-only presentation; code and wide equations scroll without widening the surrounding prose. */
final class QuizRichText extends JPanel {
    private static final Parser PARSER=Parser.builder().extensions(List.of(TablesExtension.create()))
        .includeSourceSpans(IncludeSourceSpans.BLOCKS_AND_INLINES).build();
    private static final Pattern TAG=Pattern.compile("<(/?)([A-Za-z][A-Za-z0-9:-]*)\\b[^>]*>");
    private static final Set<String> VOID_TAGS=Set.of("br","hr","img","input","meta","link","wbr");
    private static final Color CODE_BACKGROUND=Color.decode(StudyCodeBlock.BACKGROUND),CODE_LINE=new Color(0xe2e2e2);
    private final List<StudyHtmlPane> panes=new ArrayList<>();

    QuizRichText(String markdown,int font) {this(markdown,font,Color.WHITE,false,QuizPlayDesign.TEXT);}

    QuizRichText(String markdown,int font,Color background,boolean emphasized,Color ink) {
        super(new QuizQuestionCard.StackLayout(4));
        setOpaque(false);setMinimumSize(new Dimension(0,0));setAlignmentX(Component.LEFT_ALIGNMENT);
        // Parse only when constructing the active question/solution, never during paint or resize.
        String html=StudyMarkdown.render(blockCodeStatements(markdown),font);
        for(String body:blocks(html)) {
            boolean code=body.stripLeading().startsWith("<pre");
            Color paper=code?CODE_BACKGROUND:background;
            SummaryFormulaGroup group=new SummaryFormulaGroup(new SummarySkin.FormulaGroup(body,false),font,
                ignored->{},document(body,font,emphasized,ink,code),scroll->{
                    if(!code){scroll.setOpaque(false);scroll.getViewport().setOpaque(false);}
                });
            group.setMinimumSize(new Dimension(0,0));group.setAlignmentX(Component.LEFT_ALIGNMENT);
            group.textPane().setBackground(paper);
            group.textPane().setOpaque(code);
            Container viewport=SwingUtilities.getAncestorOfClass(JViewport.class,group.textPane());
            if(viewport!=null)viewport.setBackground(paper);
            if(code) {
                group.setName("quiz-code-block");group.setOpaque(true);group.setBackground(paper);
                group.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createLineBorder(CODE_LINE),new EmptyBorder(12,14,12,14)));
            } else {
                SimpleAttributeSet spacing=new SimpleAttributeSet();StyleConstants.setLineSpacing(spacing,.35f);
                ((StyledDocument)group.textPane().getDocument()).setParagraphAttributes(0,group.textPane().getDocument().getLength(),spacing,false);
            }
            panes.add(group.textPane());add(group);
        }
    }

    List<StudyHtmlPane> textPanes(){return List.copyOf(panes);}

    /** Lift complete, long inline statements; short identifiers and code inside lists/tables stay inline. */
    static String blockCodeStatements(String markdown) {
        if(markdown==null||markdown.isBlank()||markdown.indexOf('`')<0)return markdown;
        Node document=PARSER.parse(markdown);
        record Edit(int start,int end,String replacement) {}
        List<Edit> edits=new ArrayList<>();
        for(Node paragraph=document.getFirstChild();paragraph!=null;paragraph=paragraph.getNext()) {
            if(!(paragraph instanceof Paragraph))continue;
            for(Node node=paragraph.getFirstChild();node!=null;node=node.getNext()) {
                if(!(node instanceof Code code))continue;
                String literal=code.getLiteral();
                boolean statement=literal.length()>=28&&(literal.stripTrailing().endsWith(";")
                    ||literal.contains("{")&&literal.contains("}"));
                if(!statement&&literal.length()<72)continue;
                List<SourceSpan> spans=code.getSourceSpans();if(spans.isEmpty())continue;
                int start=spans.getFirst().getInputIndex(),end=spans.getLast().getInputIndex()+spans.getLast().getLength();
                int longest=0,run=0;
                for(int i=0;i<literal.length();i++){run=literal.charAt(i)=='`'?run+1:0;longest=Math.max(longest,run);}
                String fence="`".repeat(Math.max(3,longest+1));
                edits.add(new Edit(start,end,"\n\n"+fence+"\n"+literal+"\n"+fence+"\n\n"));
            }
        }
        StringBuilder result=new StringBuilder(markdown);
        for(int i=edits.size()-1;i>=0;i--){Edit edit=edits.get(i);result.replace(edit.start(),edit.end(),edit.replacement());}
        return result.toString();
    }

    /** Split only complete top-level blocks emitted by our safe Markdown renderer. */
    static List<String> blocks(String html) {
        List<String> result=new ArrayList<>();Matcher tags=TAG.matcher(html);
        int depth=0,start=0,rootStart=0;
        String rootTag="";
        while(tags.find()) {
            String tag=tags.group(2).toLowerCase(Locale.ROOT);
            if(VOID_TAGS.contains(tag)||tags.group().endsWith("/>"))continue;
            if(tags.group(1).isEmpty()) {
                if(depth++==0){rootStart=tags.start();rootTag=tag;}
            } else if(depth>0&&--depth==0) {
                String block=html.substring(rootStart,tags.end());
                if(rootTag.equals("pre")||block.contains("display='block'")) {
                    append(result,html.substring(start,rootStart));append(result,block);start=tags.end();
                }
            }
        }
        append(result,html.substring(start));return result;
    }
    private static void append(List<String> blocks,String html){if(!html.isBlank())blocks.add(html);}

    private static String document(String body,int font,boolean emphasized,Color ink,boolean codeBlock) {
        String color=String.format("#%06x",ink.getRGB()&0xffffff);
        int codeFont=Math.max(6,font-(emphasized?2:0));
        return "<html><head><style>body{font-family:Noto Sans KR,Apple SD Gothic Neo,Malgun Gothic;font-size:"
            +font+"pt;font-weight:"+(emphasized?"bold":"normal")+";color:"+color+";margin:0;}"
            +"p{margin-top:0;margin-bottom:8px;}ul,ol{margin-left:18px;}table{border-collapse:collapse;}"
            +"td,th{padding:5px;border:1px solid #d4e2f4;}strong,b{font-weight:bold;}"
            +"blockquote{border-left:3px solid #2563a6;margin-left:0;padding-left:12px;}"
            +"code{font-family:monospace;font-size:"+codeFont+"pt;font-weight:normal;font-style:normal;color:#24292f;background:"+StudyCodeBlock.INLINE_BACKGROUND+";}"
            +"pre{font-family:monospace;font-size:"+codeFont+"pt;font-weight:normal;white-space:pre;color:#24292f;"
            +(codeBlock?"margin:0;padding:0;":"background:"+StudyCodeBlock.BACKGROUND+";padding:12px;margin:8px 0;")+"}"
            +"pre code{background:"+StudyCodeBlock.BACKGROUND+";}</style></head><body>"+body+"</body></html>";
    }
}
