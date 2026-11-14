package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryDesign;
import dev.synesis.poc.ui.MistWorkspaceTheme;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.event.DocumentEvent;
import javax.swing.event.DocumentListener;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.awt.font.FontRenderContext;
import java.awt.font.LineBreakMeasurer;
import java.awt.font.TextAttribute;
import java.awt.font.TextLayout;
import java.text.AttributedString;
import java.util.List;
import java.util.*;
import java.util.function.*;

/** Figma 1:550. Local presentation with source-backed grouping; no generated data mutation. */
final class ConceptOverview extends JPanel {
    static final Color NAVY=new Color(0x002860);
    private static final Color CONCEPT_BACKGROUND=MistWorkspaceTheme.SOFT;
    private final JPanel list;
    private final JScrollPane scroll;
    private final StudyScrollActivity scrollActivity;
    private final JLabel count=label("0개 개념",12,MistWorkspaceTheme.MUTED,false);
    private final JLabel notice=new Notice();
    private final JLabel empty=label("검색 결과가 없어요.",12,MistWorkspaceTheme.MUTED,false);
    final JTextField search=new JTextField();
    private final JButton sizeButton=new JButton();
    private final ConceptOutlineNavigation outline;
    private List<Card> cards=List.of();
    private final Map<String,GroupHeader> headers=new LinkedHashMap<>();
    private final javax.swing.Timer searchDelay;
    private int layoutWidth=-1;
    private final Map<String,Bookmark> positions=new HashMap<>();
    private String product="";

    ConceptOverview(JPanel list,JScrollPane scroll,JSlider fontSize,JComboBox<String> scope,JButton more) {
        this(list,scroll,fontSize,scope,more,label("개념 정리",16,MistWorkspaceTheme.INK,true));
    }
    ConceptOverview(JPanel list,JScrollPane scroll,JSlider fontSize,JComboBox<String> scope,JButton more,JComponent title) {
        super(new BorderLayout());this.list=list;this.scroll=scroll;setBackground(Color.WHITE);
        JPanel top=new JPanel(new BorderLayout());top.setOpaque(false);
        JPanel heading=new JPanel(null){@Override public void doLayout(){
            int right=getWidth()-16;
            more.setBounds(right-32,5,32,32);
            int sizeWidth=getWidth()<380?80:104;
            sizeButton.setBounds(right-44-sizeWidth,5,sizeWidth,32);
            int titleWidth=Math.min(title.getPreferredSize().width,Math.max(0,right-52-sizeWidth-24));
            title.setBounds(24,7,titleWidth,28);
            int countX=24+titleWidth+8;
            count.setBounds(countX,11,Math.max(0,right-44-sizeWidth-countX),20);
        }};
        heading.setBackground(MistWorkspaceTheme.HEADER);
        heading.setBorder(BorderFactory.createMatteBorder(0,0,1,0,MistWorkspaceTheme.LINE));
        heading.setPreferredSize(new Dimension(1,42));heading.add(title);heading.add(count);
        chrome(sizeButton,false);sizeButton.setBackground(Color.WHITE);
        sizeButton.addActionListener(e->MistWorkspaceTheme.textSizeDialog(this,fontSize,"개념 정리 글자 크기",false));
        heading.add(sizeButton);heading.add(more);
        top.add(heading,BorderLayout.NORTH);
        JPanel toolbar=new JPanel(new BorderLayout(12,0));toolbar.setBackground(Color.WHITE);toolbar.setBorder(new EmptyBorder(14,24,14,24));toolbar.setPreferredSize(new Dimension(1,64));
        scope.setPreferredSize(new Dimension(128,36));toolbar.add(scope,BorderLayout.WEST);
        JPanel find=new JPanel(new BorderLayout(8,0));find.setOpaque(false);find.setBorder(new LibraryDesign.RoundedBorder(6,MistWorkspaceTheme.LINE,new Insets(0,12,0,12)));
        find.add(new JLabel(icon("search")),BorderLayout.WEST);
        search.setBorder(null);search.setOpaque(false);search.setFont(LibraryDesign.font(Font.PLAIN,12));search.setForeground(NAVY);search.setCaretColor(NAVY);search.putClientProperty("synesis.preserveFont",true);
        search.getAccessibleContext().setAccessibleName("개념 이름으로 찾기");
        JLayer<JTextField> entry=new JLayer<>(search,new javax.swing.plaf.LayerUI<>(){@Override public void paint(Graphics graphics,JComponent c){super.paint(graphics,c);if(search.getText().isEmpty()){graphics.setFont(search.getFont());graphics.setColor(MistWorkspaceTheme.MUTED);FontMetrics fm=graphics.getFontMetrics();graphics.drawString("개념 이름으로 찾기",0,(c.getHeight()-fm.getHeight())/2+fm.getAscent());}}});
        find.add(entry,BorderLayout.CENTER);
        JButton clearSearch=new JButton("×");chrome(clearSearch,false);
        clearSearch.setFont(LibraryDesign.font(Font.PLAIN,18));
        clearSearch.setForeground(MistWorkspaceTheme.MUTED);
        clearSearch.setBorder(new EmptyBorder(0,0,0,0));
        clearSearch.setPreferredSize(new Dimension(24,24));
        clearSearch.setToolTipText("검색어 전체 지우기");
        clearSearch.getAccessibleContext().setAccessibleName("검색어 전체 지우기");
        clearSearch.setVisible(false);find.add(clearSearch,BorderLayout.EAST);
        outline=new ConceptOutlineNavigation(scroll,this::outlineItems);
        JPanel views=new JPanel(new FlowLayout(FlowLayout.RIGHT,8,0));views.setOpaque(false);
        views.add(outline.button);
        toolbar.add(find,BorderLayout.CENTER);toolbar.add(views,BorderLayout.EAST);top.add(toolbar,BorderLayout.CENTER);add(top,BorderLayout.NORTH);
        list.setBorder(new EmptyBorder(24,36,24,36));list.setBackground(Color.WHITE);
        notice.setAlignmentX(LEFT_ALIGNMENT);empty.setAlignmentX(LEFT_ALIGNMENT);
        scroll.setBorder(null);scroll.getViewport().setBackground(Color.WHITE);scroll.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);scroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);add(scroll,BorderLayout.CENTER);
        scroll.getVerticalScrollBar().setUI(new dev.synesis.poc.ui.FadingScrollBarUI(MistWorkspaceTheme.MUTED,.38f));
        fontSize.addChangeListener(e->sizeButton.setText("Aa · "+fontSize.getValue()+"px"));sizeButton.setText("Aa · "+fontSize.getValue()+"px");
        searchDelay=new javax.swing.Timer(120,e->filter());searchDelay.setRepeats(false);
        clearSearch.addActionListener(e->{search.setText("");searchDelay.stop();filter();search.requestFocusInWindow();});
        search.getDocument().addDocumentListener(new DocumentListener(){
            private void update(){clearSearch.setVisible(!search.getText().isEmpty());find.revalidate();find.repaint();searchDelay.restart();}
            public void insertUpdate(DocumentEvent e){update();}public void removeUpdate(DocumentEvent e){update();}public void changedUpdate(DocumentEvent e){update();}
        });
        scrollActivity=new StudyScrollActivity(scroll,active->pauseReveals(list,active));
    }
    @Override public void doLayout(){
        Bookmark bookmark=layoutWidth>=0&&layoutWidth!=getWidth()?capture():null;
        layoutWidth=getWidth();super.doLayout();if(bookmark!=null)restore(bookmark);
    }
    void showCards(String product,List<Card> next,String message) {
        showCards(product,next,message,List.of());
    }
    void showCards(String product,List<Card> next,String message,List<ConceptOutline.Group> groups) {
        Bookmark bookmark=capture();boolean same=this.product.equals(product);
        if(!same){positions.put(this.product,bookmark);this.product=product;bookmark=positions.getOrDefault(product,new Bookmark(null,0,0));}
        cards=List.copyOf(next);notice.setText(message);notice.setToolTipText(message);
        List<Component> children=new ArrayList<>();children.add(notice);
        Set<String> retained=new HashSet<>();Set<Integer> placed=new HashSet<>();
        for(ConceptOutline.DisplayRow row:ConceptOutline.displayRows(groups)) {
            List<Card> members=new ArrayList<>();
            for(int index:row.concepts())if(index>=0&&index<cards.size()&&(row.heading()||placed.add(index)))members.add(cards.get(index));
            if(members.isEmpty())continue;
            if(row.heading()) {
                retained.add(row.id());GroupHeader header=headers.computeIfAbsent(row.id(),id->new GroupHeader());
                header.update(row,members);children.add(header);
            } else {
                for(Card card:members)card.outlineDepth(row.depth()+1);
                children.addAll(members);
            }
        }
        headers.keySet().retainAll(retained);
        for(int i=0;i<cards.size();i++)if(!placed.contains(i)){cards.get(i).outlineDepth(0);children.add(cards.get(i));}
        children.add(empty);
        boolean changed=!Arrays.asList(list.getComponents()).equals(children);
        if(changed){list.removeAll();for(Component child:children)list.add(child);}
        filterVisibility();list.revalidate();list.repaint();restore(bookmark);
    }
    private void filter(){Bookmark bookmark=capture();filterVisibility();list.revalidate();list.repaint();restore(bookmark);}
    private void filterVisibility(){
        String query=search.getText().strip().toLowerCase(Locale.ROOT);int shown=0;
        for(Card card:cards){boolean visible=card.title.toLowerCase(Locale.ROOT).contains(query);card.setVisible(visible);if(visible)shown++;}
        for(GroupHeader header:headers.values())header.filter();
        count.setText((query.isEmpty()?Integer.toString(cards.size()):shown+" / "+cards.size())+"개 개념");
        empty.setText(query.isEmpty()?"표시할 개념이 아직 없어요.":"검색 결과가 없어요.");empty.setVisible(shown==0);
    }
    boolean revealConcept(int index) {
        if(index<0||index>=cards.size())return false;
        Card card=cards.get(index);
        search.setText("");searchDelay.stop();filterVisibility();
        if(!card.open)card.setOpen(true);
        // A navigation jump needs the destination's final height once, rather
        // than animating/re-laying out every intervening concept card.
        card.disclosure.settle();
        list.revalidate();list.repaint();restore(new Bookmark(card.key,0,0));
        return true;
    }
    Bookmark capture(){
        int y=scroll.getViewport().getViewPosition().y;
        for(Card card:cards)if(card.isVisible()&&card.getY()<=y&&card.getY()+card.getHeight()>y)return new Bookmark(card.key,y-card.getY(),y);
        return new Bookmark(null,0,y);
    }
    void restore(Bookmark bookmark){
        // Apply the new content size and reading position together, before painting
        // or accepting another scroll event. The old list height may be stale here.
        JViewport viewport=scroll.getViewport();Dimension size=list.getPreferredSize();
        if(viewport.getWidth()>0)size.width=viewport.getWidth(); // Keep the existing wrapped reading column.
        viewport.setViewSize(size);
        list.doLayout();int y=bookmark.absolute;
        if(bookmark.key!=null)for(Card card:cards)if(card.key.equals(bookmark.key)&&card.isVisible()){
            y=card.getY()+Math.min(bookmark.offset,Math.max(0,card.getHeight()-1));break;
        }
        viewport.setViewPosition(new Point(0,Math.max(0,Math.min(y,Math.max(0,list.getHeight()-viewport.getHeight())))));
    }
    private List<ConceptOutlineNavigation.Item> outlineItems(){
        List<ConceptOutlineNavigation.Item> items=new ArrayList<>();
        // Follow the rendered rows so leaves retain their exact parent, order and search visibility.
        for(Component child:list.getComponents())if(child.isVisible()){
            if(child instanceof GroupHeader header)
                items.add(new ConceptOutlineNavigation.Item(header.title.getText(),
                    (Integer)header.getClientProperty("concept.treeDepth"),header));
            else if(child instanceof Card card)
                items.add(new ConceptOutlineNavigation.Item(card.title,card.outlineDepth,card));
        }
        return items;
    }
    void dispose(){scrollActivity.close();outline.close();searchDelay.stop();for(Card card:cards)stopReveals(card);}
    void resetDocument(){
        outline.reset();
        for(Card card:cards)stopReveals(card);
        search.setText("");searchDelay.stop();positions.clear();cards=List.of();headers.clear();product="";
    }
    record Bookmark(String key,int offset,int absolute) {}

    private static final class GroupHeader extends JPanel {
        private final JLabel title=label("",15,new Color(0x607795),false),count=label("",11,MistWorkspaceTheme.MUTED,false);
        private List<Card> members=List.of();
        GroupHeader() {
            super(new BorderLayout(12,0));setOpaque(false);setAlignmentX(LEFT_ALIGNMENT);
            setBorder(new EmptyBorder(20,0,8,0));add(title,BorderLayout.CENTER);add(count,BorderLayout.EAST);
        }
        void update(ConceptOutline.DisplayRow row,List<Card> members) {
            this.members=List.copyOf(members);
            putClientProperty("concept.treeDepth",row.depth());
            String name=row.title();
            String display=name.replaceFirst("^\\d+(?:\\.\\d+)*\\.?\\s+(?!가지|종류|유형)","");
            // A return boundary still names its actual owner. Hiding the title
            // behind "단원 이어서" loses context, especially after filtering.
            title.setText(row.number()+"  "+display);
            title.setToolTipText(name);getAccessibleContext().setAccessibleName(title.getText()+" · "+name);
            title.setFont(LibraryDesign.font(Font.PLAIN,row.continuation()?12:row.depth()==0?15:14));
            setBorder(new EmptyBorder(row.continuation()?12:20,row.depth()*16,row.continuation()?6:8,0));
            setName((row.continuation()?"concept-resume:":"concept-group:")+name);filter();
        }
        void filter() {
            long shown=members.stream().filter(Component::isVisible).count();
            setVisible(shown>0);count.setText(shown+"개 개념");
        }
        @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
    }


    /** Explicit 20px line boxes; cached wrapping never touches any concept body. */
    private static final class Notice extends JLabel {
        private static final FontRenderContext METRICS=new FontRenderContext(null,true,true);
        private final List<TextLayout> lines=new ArrayList<>();
        private String layoutText="";
        private int layoutWidth=-1;
        Notice(){setFont(LibraryDesign.font(Font.PLAIN,12));setForeground(MistWorkspaceTheme.MUTED);setAlignmentX(LEFT_ALIGNMENT);}
        private void wrap(){
            int width=Math.max(80,getParent()==null?600:getParent().getWidth()-48);String text=Objects.toString(getText(),"");
            if(width==layoutWidth&&text.equals(layoutText))return;
            layoutWidth=width;layoutText=text;lines.clear();if(text.isEmpty())return;
            AttributedString attributed=new AttributedString(text);attributed.addAttribute(TextAttribute.FONT,getFont());
            LineBreakMeasurer measure=new LineBreakMeasurer(attributed.getIterator(),METRICS);
            while(measure.getPosition()<text.length())lines.add(measure.nextLayout(width));
        }
        @Override public Dimension getPreferredSize(){wrap();return new Dimension(0,Math.max(20,lines.size()*20)+12);}
        @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        @Override protected void paintComponent(Graphics graphics){
            wrap();Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);g.setColor(getForeground());float top=0;
                for(TextLayout line:lines){line.draw(g,0,top+(20-line.getAscent()-line.getDescent())/2+line.getAscent());top+=20;}
            }finally{g.dispose();}
        }
    }

    /** Keeps a closed row cheap; reuses its exact body while its data/font/module state is unchanged. */
    static final class Card extends JPanel {
        final String key;
        private String title="",markup="",signature="";
        private final CaptionButton toggle=new CaptionButton();
        private final JButton pagesButton=new JButton();
        private final JPanel heading=new JPanel(null),body=new JPanel(new BorderLayout());
        private final Reveal disclosure;
        private final Consumer<Boolean> changed;
        private final ConceptOverview owner;
        private Supplier<JComponent> renderer;
        private boolean open,dirty=true;
        private int titleWidth=-1,titleHeight=24,headerHeight=56,outlineDepth;
        private List<Integer> pages=List.of();
        private final IntConsumer navigate;
        Card(String key,ConceptOverview owner,boolean expanded,Consumer<Boolean> changed,IntConsumer navigate){
            super(new BorderLayout());this.key=key;this.owner=owner;this.open=expanded;this.changed=changed;this.navigate=navigate;setName(key);setBackground(Color.WHITE);setAlignmentX(LEFT_ALIGNMENT);
            setBorder(new ArticleBorder());heading.setBackground(CONCEPT_BACKGROUND);heading.setPreferredSize(new Dimension(1,55));
            chrome(toggle,false);toggle.setHorizontalAlignment(SwingConstants.LEFT);toggle.setVerticalAlignment(SwingConstants.CENTER);toggle.setIcon(icon("plus"));toggle.setIconTextGap(12);toggle.setBorder(new EmptyBorder(0,16,0,8));toggle.setFont(LibraryDesign.medium(16));toggle.setForeground(MistWorkspaceTheme.INK);toggle.setBackground(CONCEPT_BACKGROUND);
            toggle.addActionListener(e->setOpen(!open));heading.add(toggle);
            chrome(pagesButton,false);pagesButton.setBackground(MistWorkspaceTheme.SOFT);pagesButton.setBorder(new EmptyBorder(0,6,0,6));pagesButton.addActionListener(e->navigatePages());heading.add(pagesButton);
            add(heading,BorderLayout.NORTH);body.setBackground(Color.WHITE);body.setBorder(new EmptyBorder(16,20,16,20));disclosure=new Reveal(body,open,owner);add(disclosure,BorderLayout.CENTER);
            if(open)toggle.setIcon(icon("expanded-minus"));
        }
        void update(String title,List<Integer> pages,String signature,Supplier<JComponent> renderer){
            this.renderer=renderer;
            if(!this.title.equals(title)){this.title=title;markup=StudyMarkdown.renderInline(title,16);toggle.setText(captionText(markup));titleWidth=-1;toggle.getAccessibleContext().setAccessibleName(title);}
            if(!this.pages.equals(pages)){this.pages=List.copyOf(pages);String refs=pages.stream().map(p->"p."+p).collect(java.util.stream.Collectors.joining(" · "));pagesButton.setText(refs);pagesButton.setToolTipText(refs);pagesButton.setVisible(!pages.isEmpty());pagesButton.getAccessibleContext().setAccessibleName("원문 이동: "+refs);titleWidth=-1;}
            if(!this.signature.equals(signature)){this.signature=signature;dirty=true;}
            if(open)ensureBody();
        }
        void outlineDepth(int value) {
            putClientProperty("concept.treeDepth",value);
            putClientProperty("concept.treeCard",Boolean.TRUE);
            putClientProperty("concept.treeAnchor",headerHeight/2);
            if(outlineDepth==value)return;outlineDepth=value;
            titleWidth=-1;revalidate();repaint();
        }
        private void ensureBody(){if(!dirty)return;body.removeAll();body.add(renderer.get(),BorderLayout.CENTER);dirty=false;}
        private void setOpen(boolean value){
            var anchor=owner.capture();open=value;if(open)ensureBody();disclosure.setOpen(open);
            toggle.setIcon(open?icon("expanded-minus"):icon("plus"));
            toggle.getAccessibleContext().setAccessibleDescription(open?"펼쳐짐":"접힘");
            changed.accept(open);revalidate();repaint();owner.restore(anchor);
        }
        private boolean articleOpen(){return open||disclosure.fraction>0;}
        private void navigatePages(){
            if(pages.size()==1){navigate.accept(pages.getFirst());return;}
            JPopupMenu menu=new JPopupMenu();for(int page:pages){JMenuItem item=new JMenuItem("p."+page);item.addActionListener(e->navigate.accept(page));menu.add(item);}menu.show(pagesButton,0,pagesButton.getHeight());
        }
        @Override public void doLayout(){
            int width=getWidth()-getInsets().left-getInsets().right, badge=pages.isEmpty()?0:Math.min(Math.max(64,pagesButton.getFontMetrics(pagesButton.getFont()).stringWidth(pagesButton.getText())+12),Math.max(64,width/3));
            int available=Math.max(48,width-badge-68);
            if(titleWidth!=available){titleWidth=available;
                titleHeight=toggle.textHeight(available);
                int next=Math.max(56,titleHeight+24);
                if(next!=headerHeight){headerHeight=next;heading.setPreferredSize(new Dimension(1,headerHeight-1));revalidate();}
            }
            putClientProperty("concept.treeAnchor",headerHeight/2);
            super.doLayout();toggle.setBounds(0,0,Math.max(0,width-badge-16),headerHeight-1);
            pagesButton.setBounds(width-badge-16,(headerHeight-24)/2,badge,24);
        }
        @Override public void paint(Graphics graphics){
            if(!articleOpen()){super.paint(graphics);return;}
            Graphics2D g=(Graphics2D)graphics.create();
            try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                int left=outlineDepth*16;g.clip(new java.awt.geom.RoundRectangle2D.Float(left,0,getWidth()-left,getHeight()-(getInsets().bottom-1),16,16));super.paint(g);
            }finally{g.dispose();}
            // Draw the antialiased outline last, outside the hard child clip.
            // Otherwise its outer corner pixels are clipped or overpainted.
            getBorder().paintBorder(this,graphics,0,0,getWidth(),getHeight());
        }
        @Override protected void paintBorder(Graphics graphics){if(!articleOpen())super.paintBorder(graphics);}
        private final class ArticleBorder extends javax.swing.border.AbstractBorder {
            @Override public Insets getBorderInsets(Component c){return articleOpen()?new Insets(1,outlineDepth*16+1,1+(int)Math.round(12*disclosure.fraction),1):new Insets(0,outlineDepth*16,1,0);}
            @Override public Insets getBorderInsets(Component c,Insets insets){Insets v=getBorderInsets(c);insets.set(v.top,v.left,v.bottom,v.right);return insets;}
            @Override public void paintBorder(Component c,Graphics graphics,int x,int y,int width,int height){
                Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(MistWorkspaceTheme.LINE);g.setStroke(new BasicStroke(1));
                    int left=outlineDepth*16;
                    if(articleOpen())g.draw(new java.awt.geom.RoundRectangle2D.Float(x+left+.5f,y+.5f,width-left-1,height-getInsets().bottom,15,15));
                    else g.fillRect(x+left,y+height-1,width-left,1);
                }finally{g.dispose();}
            }
        }
        @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
    }
    /** A clipped viewport: its child keeps its natural size throughout height-only frames.
     * No HTML documents, formula icons, images or full-card bitmaps are built by the timer. */
    static final class Reveal extends JPanel {
        private final JComponent content;
        private final ConceptOverview owner;
        private final javax.swing.Timer timer=new javax.swing.Timer(16,e->tick(System.nanoTime()));
        private boolean open,paused;
        private double fraction,from;
        private long started;
        private static final long DURATION=220_000_000L;
        Reveal(JComponent content,boolean open,ConceptOverview owner){
            super(null);this.content=content;this.owner=owner;this.open=open;fraction=open?1:0;
            paused=owner.scrollActivity.active();
            setOpaque(false);add(content);setVisible(open);timer.setCoalesce(true);
        }
        boolean isOpen(){return open;}
        void setOpen(boolean value){
            if(open==value)return;
            open=value;from=fraction;started=System.nanoTime();
            // Hidden/headless views settle immediately; no invisible background animation.
            if(getParent()==null||!getParent().isShowing()){settle();return;}
            setVisible(true);if(!paused)timer.restart();revalidate();repaint();
        }
        void pause(boolean value){
            if(paused==value)return;paused=value;
            if(value)timer.stop();
            else if(fraction!=(open?1:0)){
                if(getParent()==null||!getParent().isShowing()){settle();return;}
                from=fraction;started=System.nanoTime();timer.restart();
            }
        }
        private void tick(long now){
            if(paused)return;
            var anchor=owner.capture();
            double progress=Math.min(1,Math.max(0,(now-started)/(double)DURATION));
            double eased=1-Math.pow(1-progress,3);
            fraction=from+((open?1:0)-from)*eased;
            if(progress>=1){timer.stop();fraction=open?1:0;setVisible(open);}
            revalidate();repaint();owner.restore(anchor);
        }
        private void settle(){timer.stop();fraction=open?1:0;setVisible(open);revalidate();repaint();}
        @Override public Dimension getPreferredSize(){
            Dimension natural=content.getPreferredSize();
            return new Dimension(natural.width,(int)Math.round(natural.height*fraction));
        }
        @Override public Dimension getMinimumSize(){return new Dimension(0,0);}
        @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        @Override public void doLayout(){
            // Height of this viewport is animated, not the child's wrapping/layout height.
            int natural=content.getPreferredSize().height;
            if(content.getWidth()!=getWidth()||content.getHeight()!=natural)
                content.setBounds(0,0,getWidth(),natural);
        }
        @Override public void removeNotify(){settle();super.removeNotify();}
    }
    private static void stopReveals(Container parent){
        for(Component child:parent.getComponents()){
            if(child instanceof Reveal reveal)reveal.settle();
            if(child instanceof Container container)stopReveals(container);
        }
    }
    private static void pauseReveals(Container parent,boolean paused){
        for(Component child:parent.getComponents()){
            if(child instanceof Reveal reveal)reveal.pause(paused);
            if(child instanceof Container nested)pauseReveals(nested,paused);
        }
    }
    /** BasicHTML drops the bundled font's weight. Paint cached lines with the real Medium face. */
    private static final class CaptionButton extends JButton {
        private static final FontRenderContext METRICS=new FontRenderContext(null,true,true);
        private final List<TextLayout> lines=new ArrayList<>();
        private int measuredWidth=-1;
        private String measuredText="";
        int textHeight(int width){
            String text=Objects.toString(getText(),"");
            if(measuredWidth!=width||!measuredText.equals(text)){
                measuredWidth=width;measuredText=text;lines.clear();
                if(!text.isEmpty()){
                    AttributedString label=new AttributedString(text);label.addAttribute(TextAttribute.FONT,getFont());
                    LineBreakMeasurer measure=new LineBreakMeasurer(label.getIterator(),METRICS);
                    while(measure.getPosition()<text.length())lines.add(measure.nextLayout(Math.max(1,width)));
                }
            }
            return Math.max(24,lines.size()*24);
        }
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);g.setRenderingHint(RenderingHints.KEY_FRACTIONALMETRICS,RenderingHints.VALUE_FRACTIONALMETRICS_ON);
                g.setColor(getModel().isRollover()?MistWorkspaceTheme.SOFT:getBackground());g.fillRect(0,0,getWidth(),getHeight());
                if(getIcon()!=null)getIcon().paintIcon(this,g,16,(getHeight()-16)/2);
                int height=textHeight(Math.max(1,getWidth()-44-8));float top=(getHeight()-height)/2f;g.setColor(getForeground());
                for(TextLayout line:lines){line.draw(g,44,top+(24-line.getAscent()-line.getDescent())/2+line.getAscent());top+=24;}
            }finally{g.dispose();}
        }
    }
    private static String captionText(String markup){
        try{var kit=new javax.swing.text.html.HTMLEditorKit();var doc=kit.createDefaultDocument();kit.read(new java.io.StringReader("<html><body>"+markup+"</body></html>"),doc,0);return doc.getText(0,doc.getLength()).strip().replace('\n',' ');}
        catch(java.io.IOException|javax.swing.text.BadLocationException error){throw new IllegalArgumentException("Invalid concept label",error);}
    }
    /** The 560px Figma action row wraps intact controls in narrower study panes. */
    static JPanel actions(JButton source,JButton easy,JButton tutor){
        JPanel row=new JPanel(null){
            private int lastHeight=-1;
            private int arrange(boolean place){int x=0,y=0,width=Math.max(1,getWidth());
                int fixed=0,controls=0;
                for(Component child:getComponents())if(child.isVisible()){controls++;if(child!=source)fixed+=child.getPreferredSize().width;}
                int flexible=source!=null&&width>=fixed+(controls-1)*8+128?width-fixed-(controls-1)*8:-1;
                for(Component child:getComponents())if(child.isVisible()){
                    int w=Math.min(width,child==source&&flexible>0?flexible:child.getPreferredSize().width);if(x>0&&x+w>width){x=0;y+=44;}
                    if(place)child.setBounds(x,y,w,36);x+=w+8;
                }
                return y+36;
            }
            @Override public void doLayout(){int height=arrange(true);if(height!=lastHeight){lastHeight=height;revalidate();}}
            @Override public Dimension getPreferredSize(){return new Dimension(1,arrange(false));}
            @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        };
        row.setOpaque(false);if(easy!=null)row.add(easy);row.add(tutor);if(source!=null)row.add(source);return row;
    }
    static JButton sourceButton(List<Integer> pages,IntConsumer navigate){
        String text="원문 "+pages.stream().map(p->"p."+p).collect(java.util.stream.Collectors.joining(" · "))+"에서 확인";
        Icon arrow=icon("source-arrow");
        JButton button=new JButton(text){
            private Font shownFont;
            private String shownText,shownCaption;
            private int shownWidth=-1;
            private FontRenderContext shownContext;
            @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);g.setFont(getFont());g.setColor(getForeground());
                FontMetrics metrics=g.getFontMetrics();String currentText=getText();int limit=Math.max(1,getWidth()-24);
                Font measuredFont=metrics.getFont();FontRenderContext context=metrics.getFontRenderContext();
                if(shownCaption==null||shownWidth!=limit||!Objects.equals(shownFont,measuredFont)
                    ||!Objects.equals(shownText,currentText)||!Objects.equals(shownContext,context)){
                    String shown=currentText;
                    if(metrics.stringWidth(shown)>limit){while(!shown.isEmpty()&&metrics.stringWidth(shown+"…")>limit)shown=shown.substring(0,shown.length()-1);shown+="…";}
                    shownFont=measuredFont;shownText=currentText;shownWidth=limit;shownContext=context;shownCaption=shown;
                }
                g.drawString(shownCaption,0,(getHeight()-metrics.getHeight())/2+metrics.getAscent());arrow.paintIcon(this,g,getWidth()-16,(getHeight()-16)/2);
            }finally{g.dispose();}
        }};
        actionButton(button,232,false);button.setFont(LibraryDesign.font(Font.PLAIN,12));button.setToolTipText(text);
        button.addActionListener(e->{
            if(pages.size()==1){navigate.accept(pages.getFirst());return;}
            JPopupMenu menu=new JPopupMenu();for(int page:pages){JMenuItem item=new JMenuItem("p."+page);item.addActionListener(event->navigate.accept(page));menu.add(item);}menu.show(button,0,button.getHeight());
        });return button;
    }
    static void actionButton(JButton button,int width,boolean outlined){chrome(button,outlined);button.putClientProperty("concept.radius",8);button.setBackground(Color.WHITE);button.setFont(LibraryDesign.medium(12));button.setPreferredSize(new Dimension(width,36));}
    static JLabel label(String text,int size,Color color,boolean bold){JLabel label=new JLabel(text);label.setForeground(color);label.setFont(LibraryDesign.font(bold?Font.BOLD:Font.PLAIN,size));label.putClientProperty("synesis.preserveFont",true);return label;}
    static void chrome(AbstractButton button,boolean outlined){
        MistWorkspaceTheme.button(button,outlined);button.setForeground(NAVY);button.setFont(LibraryDesign.font(Font.PLAIN,12));button.setUI(new BasicButtonUI(){@Override public void paint(Graphics graphics,JComponent c){Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);int arc=button.getClientProperty("concept.radius") instanceof Integer radius?radius*2:12;g.setColor(button.getModel().isRollover()?MistWorkspaceTheme.SOFT:button.getBackground());g.fillRoundRect(0,0,c.getWidth(),c.getHeight(),arc,arc);if(outlined){g.setColor(MistWorkspaceTheme.LINE);g.drawRoundRect(0,0,c.getWidth()-1,c.getHeight()-1,arc,arc);}}finally{g.dispose();}super.paint(graphics,c);}});
    }
    private static final Map<String,BufferedImage> ICONS=new HashMap<>();
    private static final Map<String,Icon> DEVICE_ICONS=new HashMap<>();
    static synchronized Icon icon(String name){return DEVICE_ICONS.computeIfAbsent(name,k->{BufferedImage image=ICONS.computeIfAbsent(k,asset->{try(var in=ConceptOverview.class.getResourceAsStream("/dev/synesis/poc/concept/"+asset+".png")){if(in==null)throw new IllegalStateException("Missing concept icon "+asset);return ImageIO.read(in);}catch(java.io.IOException e){throw new IllegalStateException(e);}});return new dev.synesis.poc.ui.DeviceImageIcon(image,16,16);});}
}
