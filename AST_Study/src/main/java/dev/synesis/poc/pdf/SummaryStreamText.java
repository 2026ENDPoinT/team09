package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import java.awt.*;
import java.awt.geom.Rectangle2D;
import java.text.BreakIterator;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.function.LongSupplier;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.text.*;

/** Append-only, selectable draft text. Animation changes paint color, never the document. */
final class SummaryStreamText {
    static final String PROPERTY="synesis.summaryStreamText";
    static final long FADE_NANOS=220_000_000L, STAGGER_NANOS=80_000_000L;
    static final int MAX_FADING_GLYPHS=160;
    private record Birth(int from,int to,long at) {}
    private record Heading(int from,int to) {}
    private record Normalized(String text,List<Heading> headings) {}
    private final StudyHtmlPane pane;
    private final LongSupplier clock;
    private final ArrayDeque<Birth> births=new ArrayDeque<>();
    private final DefaultStyledDocument document=new DefaultStyledDocument();
    private final Color[] palette=new Color[13];
    private String text="";
    private String acceptedMarkdown,acceptedTitle;
    private List<Heading> headings=List.of();
    private int fontSize;
    private SimpleAttributeSet bodyStyle=new SimpleAttributeSet();
    private long edits,insertedCharacters;

    SummaryStreamText(StudyHtmlPane pane){this(pane,System::nanoTime);}
    SummaryStreamText(StudyHtmlPane pane,LongSupplier clock){
        this.pane=pane;this.clock=clock;
        pane.putClientProperty(PROPERTY,this);
        pane.setEditorKit(new StyledEditorKit(){
            private final ViewFactory factory=element->switch(element.getName()) {
                case AbstractDocument.ContentElementName->new FadingLabel(element);
                case AbstractDocument.ParagraphElementName->new ParagraphView(element){
                    @Override protected javax.swing.SizeRequirements calculateMinorAxisRequirements(int axis,javax.swing.SizeRequirements result){
                        result=super.calculateMinorAxisRequirements(axis,result);result.minimum=0;return result;
                    }
                };
                case AbstractDocument.SectionElementName->new BoxView(element,View.Y_AXIS);
                case StyleConstants.ComponentElementName->new ComponentView(element);
                case StyleConstants.IconElementName->new IconView(element);
                default->new LabelView(element);
            };
            @Override public ViewFactory getViewFactory(){return factory;}
        });
        pane.setDocument(document);pane.setEditable(false);pane.setOpaque(true);
        pane.setBackground(Color.WHITE);pane.setForeground(Color.BLACK);
        for(int i=0;i<palette.length;i++) {
            double opacity=i/12d;Color bg=pane.getBackground(),fg=pane.getForeground();
            palette[i]=new Color((int)Math.round(bg.getRed()*(1-opacity)+fg.getRed()*opacity),
                (int)Math.round(bg.getGreen()*(1-opacity)+fg.getGreen()*opacity),
                (int)Math.round(bg.getBlue()*(1-opacity)+fg.getBlue()*opacity));
        }
        document.putProperty("multiByte",Boolean.FALSE);
        pane.setBorder(new EmptyBorder(4,24,8,24));pane.setMargin(new Insets(0,0,0,0));
        if(pane.getCaret()instanceof DefaultCaret caret)caret.setUpdatePolicy(DefaultCaret.NEVER_UPDATE);
    }
    static SummaryStreamText of(JEditorPane pane){return pane.getClientProperty(PROPERTY)instanceof SummaryStreamText value?value:null;}

    boolean accept(String markdown,String title,int size){
        // Other units may update while this draft stays unchanged. Reuse its
        // normalized text as well as its document instead of parsing it again.
        if(fontSize==size&&Objects.equals(acceptedMarkdown,markdown)&&Objects.equals(acceptedTitle,title))return false;
        Normalized normalized=normalize(markdown,title);String next=normalized.text();
        boolean fontChanged=fontSize!=size,headingsChanged=!headings.equals(normalized.headings());
        if(next.equals(text)&&!fontChanged&&!headingsChanged){acceptedMarkdown=markdown;acceptedTitle=title;return false;}
        int common=0,limit=Math.min(text.length(),next.length());
        while(common<limit&&text.charAt(common)==next.charAt(common))common++;
        if(common>0&&common<next.length()&&Character.isLowSurrogate(next.charAt(common)))common--;
        boolean append=common==text.length();
        if(!append)births.clear();
        try {
            if(fontChanged) {
                fontSize=size;Font font=MistWorkspaceTheme.font(Font.PLAIN,size);pane.setFont(font);
                bodyStyle=new SimpleAttributeSet();StyleConstants.setFontFamily(bodyStyle,font.getFamily());
                StyleConstants.setFontSize(bodyStyle,size);StyleConstants.setBold(bodyStyle,false);StyleConstants.setForeground(bodyStyle,pane.getForeground());
            }
            if(common<text.length())document.remove(common,text.length()-common);
            if(common<next.length()) {
                String added=next.substring(common);document.insertString(common,added,bodyStyle);insertedCharacters+=added.length();
            }
            if(fontChanged) {
                document.setLogicalStyle(0,null);document.setCharacterAttributes(0,document.getLength(),bodyStyle,false);
            }
            // Appended paragraphs inherit these attributes. Reapplying them to
            // the last paragraph per delta would invalidate all its old rows.
            if(fontChanged) {
                SimpleAttributeSet paragraph=new SimpleAttributeSet();StyleConstants.setLineSpacing(paragraph,.42f);
                StyleConstants.setSpaceAbove(paragraph,0);StyleConstants.setSpaceBelow(paragraph,Math.max(6,size*.48f));
                document.setParagraphAttributes(0,document.getLength(),paragraph,false);
            }
            if(common<next.length()) {
                remember(next,common,clock.getAsLong());
            }
            if(headingsChanged&&!fontChanged)for(Heading old:headings) {
                int end=Math.min(old.to(),document.getLength());
                if(old.from()<end){SimpleAttributeSet normal=new SimpleAttributeSet();StyleConstants.setBold(normal,false);StyleConstants.setFontSize(normal,size);document.setCharacterAttributes(old.from(),end-old.from(),normal,false);}
            }
            for(Heading heading:normalized.headings())if(fontChanged||headingsChanged||heading.to()>common) {
                SimpleAttributeSet style=new SimpleAttributeSet();StyleConstants.setBold(style,true);StyleConstants.setFontSize(style,Math.round(size*1.14f));
                document.setCharacterAttributes(heading.from(),heading.to()-heading.from(),style,false);
            }
            headings=normalized.headings();text=next;acceptedMarkdown=markdown;acceptedTitle=title;
            edits++;pane.contentEdited();pane.revalidate();pane.repaint();return true;
        }catch(BadLocationException invalid){throw new IllegalStateException("Draft document changed outside its owner",invalid);}
    }
    private void remember(String value,int from,long now){
        // Keep at most a short recent tail. A large arriving chunk never becomes
        // a long artificial typing queue and surrogate/grapheme boundaries stay whole.
        BreakIterator iterator=BreakIterator.getCharacterInstance(Locale.ROOT);
        int tail=Math.max(from,value.length()-MAX_FADING_GLYPHS*2);
        if(tail>0&&Character.isLowSurrogate(value.charAt(tail)))tail--;
        iterator.setText(value.substring(tail));
        ArrayDeque<Birth> added=new ArrayDeque<>();int left=iterator.first(),right;
        while((right=iterator.next())!=BreakIterator.DONE){
            if(tail+left>=from)added.addLast(new Birth(tail+left,tail+right,now));left=right;
            if(added.size()>MAX_FADING_GLYPHS)added.removeFirst();
        }
        int n=added.size(),i=0;
        for(Birth birth:added)births.addLast(new Birth(birth.from(),birth.to(),now+(n<=1?0:STAGGER_NANOS*i++/(n-1))));
        while(births.size()>MAX_FADING_GLYPHS)births.removeFirst();prune(now);
    }
    private void prune(long now){while(!births.isEmpty()&&now-births.getFirst().at()>=FADE_NANOS)births.removeFirst();}
    boolean active(long now){prune(now);return !births.isEmpty();}
    void finish(){if(!births.isEmpty()){births.clear();pane.repaint();}}
    void repaintRecent(long now){
        boolean had=!births.isEmpty();
        if(!active(now)){if(had)pane.repaint(pane.getVisibleRect());return;}
        Rectangle visible=pane.getVisibleRect();if(visible.isEmpty())return;
        try {
            Rectangle2D first=pane.modelToView2D(births.getFirst().from());
            Rectangle2D last=pane.modelToView2D(Math.min(document.getLength(),births.getLast().to()));
            if(first!=null&&last!=null) {
                Rectangle dirty=new Rectangle(visible.x,(int)first.getY(),visible.width,
                    Math.max(1,(int)Math.ceil(last.getMaxY()-first.getY())+2));
                dirty=dirty.intersection(visible);if(!dirty.isEmpty())pane.repaint(dirty);return;
            }
        }catch(BadLocationException ignored){}
        pane.repaint(visible);
    }
    int recentGlyphs(){return births.size();}
    long edits(){return edits;}
    long insertedCharacters(){return insertedCharacters;}
    private Color color(Birth birth,long now){
        double t=Math.max(0,Math.min(1,(now-birth.at())/(double)FADE_NANOS));
        // Twelve paint buckets group adjacent glyphs; no span/style allocation per frame.
        return palette[(int)Math.round(t*(2-t)*12)];
    }
    private final class FadingLabel extends LabelView {
        FadingLabel(Element element){super(element);}
        @Override public void paint(Graphics graphics,Shape allocation){
            long now=clock.getAsLong();prune(now);
            int from=getStartOffset(),to=Math.min(getEndOffset(),document.getLength());
            if(births.isEmpty()||to<=births.getFirst().from()||from>=births.getLast().to()
                ||pane.getSelectionStart()!=pane.getSelectionEnd()){super.paint(graphics,allocation);return;}
            checkPainter();Graphics copy=graphics.create();int at=from,runFrom=-1,runTo=-1;Color runColor=null;
            try {
                for(Birth birth:births){
                    if(birth.to()<=at)continue;if(birth.from()>=to)break;
                    int left=Math.max(at,birth.from()),right=Math.min(to,birth.to());
                    Color next=color(birth,now);
                    if(runFrom>=0&&(at<left||next!=runColor)) {
                        copy.setColor(runColor);getGlyphPainter().paint(this,copy,allocation,runFrom,runTo);runFrom=-1;
                    }
                    if(at<left){copy.setColor(getForeground());getGlyphPainter().paint(this,copy,allocation,at,left);}
                    if(runFrom<0){runFrom=left;runColor=next;}runTo=right;at=right;
                }
                if(runFrom>=0){copy.setColor(runColor);getGlyphPainter().paint(this,copy,allocation,runFrom,runTo);}
                if(at<to){copy.setColor(getForeground());getGlyphPainter().paint(this,copy,allocation,at,to);}
            }finally{copy.dispose();}
        }
    }
    static String plain(String markdown,String title){
        return normalize(markdown,title).text();
    }
    private static Normalized normalize(String markdown,String title){
        String value=StudyMarkdown.withoutControlChars(markdown);StringBuilder out=new StringBuilder(value.length());boolean first=true;
        List<Heading> headings=new ArrayList<>();
        for(String paragraph:value.split("\n\n",-1)) {
            boolean heading=false;
            if(paragraph.matches("#{1,6} [^\n]+")) {
                String label=paragraph.substring(paragraph.indexOf(' ')+1);
                if(first&&label.strip().equals(title.strip())){first=false;continue;}
                paragraph=label;heading=true;
            }
            if(!out.isEmpty())out.append("\n\n");int at=out.length();out.append(paragraph);
            if(heading)headings.add(new Heading(at,out.length()));first=false;
        }
        return new Normalized(out.toString(),List.copyOf(headings));
    }
}
