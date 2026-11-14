package dev.synesis.poc.pdf;

import org.scilab.forge.jlatexmath.TeXConstants;
import org.scilab.forge.jlatexmath.TeXFormula;
import org.scilab.forge.jlatexmath.TeXIcon;

import javax.swing.JEditorPane;
import javax.swing.SwingUtilities;
import javax.swing.text.AttributeSet;
import javax.swing.text.Element;
import javax.swing.text.GlyphView;
import javax.swing.text.Position;
import javax.swing.text.TabExpander;
import javax.swing.text.View;
import javax.swing.text.ViewFactory;
import javax.swing.text.html.HTML;
import javax.swing.text.html.HTMLEditorKit;
import java.awt.Color;
import java.awt.AlphaComposite;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.RenderingHints;
import java.awt.Shape;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Keeps the original Swing prose layout and paints formulas as resolution-independent vectors. */
final class StudyHtmlPane extends JEditorPane {
    private final boolean wordWrap;
    private boolean readingSkin;
    private boolean blackText;
    private long contentRevision;
    private boolean coordinatedSelection;
    private String easyPressedAction;
    private java.awt.Point easyPressedPoint;
    private long easyPressedRevision;
    private boolean easyDragged,easyHeaderHovered;
    private static final Pattern MATH = Pattern.compile("(?s)<math\\b([^>]*)>.*?</math>");
    private static final Pattern MATH_WRAPPER = Pattern.compile("(?s)<span style='display:(?:inline-block;max-width:100%;overflow-x:auto;vertical-align:middle|block;max-width:100%;overflow-x:auto;overflow-y:hidden)'>(<math\\b[^>]*>.*?</math>)</span>");
    private static final Pattern ATTRIBUTE = Pattern.compile("([a-zA-Z-]+)='([^']*)'");
    private static final Pattern FONT_SIZE = Pattern.compile("font-size:([0-9]+)pt");
    private static final AtomicLong NEXT_ID = new AtomicLong();
    private static final Set<StudyHtmlPane> PANES = Collections.newSetFromMap(new WeakHashMap<>());
    private static final Map<String, MathInfo> MATH_CACHE = new LinkedHashMap<>(256, .75f, true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String, MathInfo> eldest) {
            return size() > 4096;
        }
    };
    private record MathKey(String tex,boolean display,int size,Color foreground) {}
    private static final Map<MathKey,TeXIcon> FORMULA_ICONS=new LinkedHashMap<>(128,.75f,true) {
        @Override protected boolean removeEldestEntry(Map.Entry<MathKey,TeXIcon> eldest){return size()>256;}
    };

    @Override protected void processMouseEvent(MouseEvent event) {
        TutorScrollKeeper keeper=TutorScrollKeeper.owner(this);
        if(keeper!=null && event.getID()==MouseEvent.MOUSE_PRESSED)keeper.userInput();
        if(event.getID()==MouseEvent.MOUSE_PRESSED) {
            easyPressedAction=readingSkin&&SwingUtilities.isLeftMouseButton(event)?SummarySkin.easyActionAt(this,event.getPoint()):null;
            easyPressedPoint=event.getPoint();easyPressedRevision=contentRevision;easyDragged=false;
        }
        if(readingSkin&&event.getID()==MouseEvent.MOUSE_CLICKED&&SwingUtilities.isLeftMouseButton(event)) {
            String action=SummarySkin.easyActionAt(this,event.getPoint());
            if(action!=null || easyPressedAction!=null) {
                boolean activate=event.getClickCount()==1&&!easyDragged&&easyPressedRevision==contentRevision
                    &&action!=null&&action.equals(easyPressedAction);
                easyPressedAction=null;event.consume();
                if(activate)fireHyperlinkUpdate(new javax.swing.event.HyperlinkEvent(this,
                    javax.swing.event.HyperlinkEvent.EventType.ACTIVATED,null,action));
                return; // Native text/image links must not toggle the same header a second time.
            }
        }
        super.processMouseEvent(event);
    }
    @Override protected void processMouseMotionEvent(MouseEvent event) {
        TutorScrollKeeper keeper=TutorScrollKeeper.owner(this);
        if(keeper!=null && event.getID()==MouseEvent.MOUSE_DRAGGED)keeper.userInput();
        if(event.getID()==MouseEvent.MOUSE_DRAGGED&&easyPressedAction!=null&&easyPressedPoint!=null
            &&easyPressedPoint.distanceSq(event.getPoint())>=9)easyDragged=true;
        boolean moving=event.getID()==MouseEvent.MOUSE_MOVED;
        boolean overHeader=readingSkin&&moving&&SummarySkin.easyActionAt(this,event.getPoint())!=null;
        if(moving&&easyHeaderHovered&&!overHeader)setCursor(java.awt.Cursor.getPredefinedCursor(java.awt.Cursor.TEXT_CURSOR));
        super.processMouseMotionEvent(event);
        if(keeper!=null && event.getID()==MouseEvent.MOUSE_DRAGGED && !coordinatedSelection)revealUserCaret();
        if(overHeader)setCursor(java.awt.Cursor.getPredefinedCursor(java.awt.Cursor.HAND_CURSOR));
        if(moving)easyHeaderHovered=overHeader;
    }

    StudyHtmlPane() {
        this(false);
    }

    StudyHtmlPane(boolean wordWrap) {
        super();
        this.wordWrap = wordWrap;
        setContentType("text/html");
        setEditorKit(new MathEditorKit());
        javax.swing.text.DefaultCaret selectionCaret=new dev.synesis.poc.ui.ReadOnlyCaret() {
            private boolean managed(){return getClientProperty(StudySelectionActions.class)!=null;}
            @Override public void mousePressed(MouseEvent event) {
                if(!managed()){coordinatedSelection=false;super.mousePressed(event);}
            }
            @Override public void mouseDragged(MouseEvent event){if(!managed())super.mouseDragged(event);}
            @Override public void mouseReleased(MouseEvent event){if(!managed())super.mouseReleased(event);}
            @Override public void mouseClicked(MouseEvent event){if(!managed())super.mouseClicked(event);}
            @Override public void setSelectionVisible(boolean visible) {
                // Focus can move between cached panes while one logical selection
                // spans all of them. Keep its highlight until the range is cleared.
                super.setSelectionVisible(visible||coordinatedSelection&&managed()&&getDot()!=getMark());
            }
            @Override protected void adjustVisibility(Rectangle bounds) {
                // Several selected documents must not each scroll their caret into view.
                // Keyboard navigation restores the usual caret scrolling below.
                // Chat owns its viewport; document replacement must not reveal an old caret at zero.
                if(!coordinatedSelection && TutorScrollKeeper.owner(StudyHtmlPane.this)==null)
                    super.adjustVisibility(bounds);
            }
        };
        selectionCaret.setBlinkRate(getCaret().getBlinkRate());setCaret(selectionCaret);
        synchronized (PANES) { PANES.add(this); }
        // MathView paints its own selection, so caret changes must repaint that overlay.
        addCaretListener(event -> repaint());
        addMouseListener(new MouseAdapter() {
            @Override public void mousePressed(MouseEvent event) {
                if(getClientProperty(StudySelectionActions.class)!=null)return;
                if(!SwingUtilities.isLeftMouseButton(event))return;
                java.util.List<StudyHtmlPane> others;
                synchronized (PANES) { others = new ArrayList<>(PANES); }
                for(StudyHtmlPane pane:others)
                    if(pane!=StudyHtmlPane.this && pane.getSelectionStart()!=pane.getSelectionEnd())
                        pane.clearSelectionAt(pane.getCaretPosition());
            }
            @Override public void mouseClicked(MouseEvent event) {
                if(getClientProperty(StudySelectionActions.class)!=null)return;
                if (!SwingUtilities.isLeftMouseButton(event) || event.getClickCount() != 1
                    || getSelectionStart() == getSelectionEnd()) return;
                clearSelectionAt(viewToModel2D(event.getPoint()));
            }
        });
    }

    void clearSelectionAt(int offset) {
        if(getClientProperty(StudySelectionActions.class)!=null)setStudySelection(offset,offset);
        else setCaretPosition(Math.max(0, Math.min(getDocument().getLength(), offset)));
        repaint();
    }
    static void clearStudySelections() {
        java.util.List<StudyHtmlPane> panes;
        synchronized(PANES){panes=new ArrayList<>(PANES);}
        for(StudyHtmlPane pane:panes)if(pane.getSelectionStart()!=pane.getSelectionEnd())
            pane.setStudySelection(pane.getCaretPosition(),pane.getCaretPosition());
    }
    void setStudySelection(int start,int end) {
        coordinatedSelection=true;
        int length=getDocument().getLength();start=Math.max(0,Math.min(length,start));end=Math.max(0,Math.min(length,end));
        if(getCaret().getMark()!=start)setCaretPosition(start);
        if(getCaret().getDot()!=end)moveCaretPosition(end);
        getCaret().setSelectionVisible(start!=end);
    }
    @Override protected void processKeyEvent(java.awt.event.KeyEvent event) {
        if(event.getID()==java.awt.event.KeyEvent.KEY_PRESSED)coordinatedSelection=false;
        TutorScrollKeeper keeper=TutorScrollKeeper.owner(this);
        boolean navigation=event.getID()==java.awt.event.KeyEvent.KEY_PRESSED && switch(event.getKeyCode()) {
            case java.awt.event.KeyEvent.VK_UP,java.awt.event.KeyEvent.VK_DOWN,
                java.awt.event.KeyEvent.VK_LEFT,java.awt.event.KeyEvent.VK_RIGHT,
                java.awt.event.KeyEvent.VK_PAGE_UP,java.awt.event.KeyEvent.VK_PAGE_DOWN,
                java.awt.event.KeyEvent.VK_HOME,java.awt.event.KeyEvent.VK_END -> true;
            default -> false;
        };
        if(keeper!=null && navigation)keeper.userInput();
        super.processKeyEvent(event);
        if(keeper!=null && navigation)revealUserCaret();
    }

    private void revealUserCaret() {
        try {
            var bounds=modelToView2D(getCaretPosition());
            if(bounds!=null)scrollRectToVisible(bounds.getBounds());
        } catch(javax.swing.text.BadLocationException ignored) {}
    }

    @Override public void setText(String text) {
        boolean nextBlackText=text!=null&&text.contains("<body data-synesis-black-text='true'>");
        blackText=nextBlackText;
        String html=StudyEmoji.decorate(prepareForSwing(text,
            Boolean.TRUE.equals(getClientProperty("synesis.assistantDark"))));
        // Parse off-view. Editing the mounted HTMLDocument exposes intermediate
        // table rows to synchronous viewport/size listeners before Swing has
        // rebuilt its column grid (TableView.RowView.layoutMajorAxis can crash).
        // Publish one complete tree, including for partial streaming Markdown.
        javax.swing.text.Document next=getEditorKit().createDefaultDocument();
        try {getEditorKit().read(new java.io.StringReader(html==null?"":html),next,0);}
        catch(java.io.IOException | javax.swing.text.BadLocationException failure) {
            throw new IllegalArgumentException("학습 본문을 표시하지 못했어요.",failure);
        }
        if(wordWrap)next.putProperty("multiByte",Boolean.FALSE);
        contentRevision++;
        setDocument(next);
        // Swing's multibyte line iterator permits breaks between Korean
        // syllables. Select its whitespace iterator for summary prose instead.
    }

    void setReadingSkin(boolean enabled) {
        if(readingSkin==enabled)return;
        readingSkin=enabled;
        // A fresh document prevents skin rules (e.g. list-style:none) leaking into legacy mode.
        setDocument(getEditorKit().createDefaultDocument());
        contentRevision++;
    }
    boolean blackText(){return blackText;}
    long contentRevision() {return contentRevision;}
    /** Incremental draft edits invalidate height/selection caches without resetting HTML. */
    void contentEdited() {contentRevision++;}

    /** Export source math, not a fragment of its visually selected fallback label. */
    String selectionMarkdown(int from,int to) {
        if(!(getDocument() instanceof javax.swing.text.html.HTMLDocument document))return getSelectedText();
        int end=Math.min(document.getLength(),Math.max(from,to));
        int position=Math.max(0,Math.min(from,to));
        StringBuilder result=new StringBuilder();String previousMath=null;
        try {
            while(position<end) {
                Element element=document.getCharacterElement(position);
                int next=Math.min(end,element.getEndOffset());
                AttributeSet span=element.getAttributes().getAttribute(HTML.Tag.SPAN) instanceof AttributeSet value?value:null;
                Object tex=span==null?null:span.getAttribute("data-study-tex");
                if(tex!=null) {
                    String identity=String.valueOf(span.getAttribute(HTML.Attribute.ID));
                    if(!identity.equals(previousMath)) {
                        boolean display="block".equals(span.getAttribute("data-study-display"));
                        result.append(display?"\n$$\n":"$").append(tex).append(display?"\n$$\n":"$");
                    }
                    previousMath=identity;
                } else {
                    result.append(document.getText(position,next-position));previousMath=null;
                }
                position=next;
            }
        } catch(javax.swing.text.BadLocationException invalidated) {return "";}
        return result.toString().replace('\u00a0',' ').strip();
    }

    static String prepareForSwing(String html) {
        return prepareForSwing(html,false);
    }
    private static String prepareForSwing(String html,boolean assistantDark) {
        boolean blackText=html!=null&&html.contains("<body data-synesis-black-text='true'>");
        html=StudyCodeBlock.decorate(html);
        if(assistantDark&&html!=null)html=AssistantChatTheme.document(html);
        if (html == null || !html.contains("<math ")) return html;
        Matcher wrapper = MATH_WRAPPER.matcher(html);
        StringBuffer unwrapped = new StringBuffer();
        while(wrapper.find())wrapper.appendReplacement(unwrapped,Matcher.quoteReplacement(wrapper.group(1)));
        wrapper.appendTail(unwrapped);
        html = unwrapped.toString();
        Matcher matcher = MATH.matcher(html);
        StringBuffer result = new StringBuffer();
        while (matcher.find()) {
            Map<String, String> attributes = new java.util.HashMap<>();
            Matcher attribute = ATTRIBUTE.matcher(matcher.group(1));
            while (attribute.find()) attributes.put(attribute.group(1), decode(attribute.group(2)));
            String tex = attributes.getOrDefault("aria-label", "");
            String label = attributes.getOrDefault("data-plain", tex);
            if (tex.isBlank() || label.isBlank()) {
                matcher.appendReplacement(result, Matcher.quoteReplacement(escape(label)));
                continue;
            }
            String id = "synesis-math-" + NEXT_ID.incrementAndGet();
            boolean display = "block".equals(attributes.get("display"));
            // Keep source on the document itself; selection survives icon-cache eviction
            // and even a formula that cannot be drawn by the local TeX renderer.
            String sourceSpan="<span id='"+id+"' data-study-tex='"+escape(tex)
                +"' data-study-display='"+(display?"block":"inline")+"'>"+escape(label)+"</span>";
            try {
                Matcher size = FONT_SIZE.matcher(attributes.getOrDefault("style", ""));
                int fontSize = size.find() ? Integer.parseInt(size.group(1)) : 16;
                boolean dark = attributes.getOrDefault("style", "").contains("#f3f5f9");
                Color foreground=blackText?Color.BLACK:dark?new Color(0xf3f5f9):new Color(0x182234);
                MathKey key=new MathKey(tex,display,fontSize,foreground);
                TeXIcon icon;
                synchronized(FORMULA_ICONS) {
                    icon=FORMULA_ICONS.get(key);
                    if(icon==null) {
                        icon=new TeXFormula(tex).createTeXIcon(
                            display?TeXConstants.STYLE_DISPLAY:TeXConstants.STYLE_TEXT,
                            fontSize*(display?1.20f:1.28f));
                        icon.setForeground(foreground);
                        if(tex.length()<=4096)FORMULA_ICONS.put(key,icon);
                    }
                }
                synchronized (MATH_CACHE) { MATH_CACHE.put(id, new MathInfo(icon, display)); }
                String replacement = sourceSpan;
                if (display && !attributes.containsKey("data-study-card")) replacement = "<br>" + replacement + "<br>";
                matcher.appendReplacement(result, Matcher.quoteReplacement(replacement));
            } catch (Exception | LinkageError error) {
                matcher.appendReplacement(result, Matcher.quoteReplacement(sourceSpan));
            }
        }
        matcher.appendTail(result);
        return result.toString();
    }

    private static String decode(String value) {
        return value.replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", "\"").replace("&#39;", "'").replace("&amp;", "&");
    }

    private static String escape(String value) {
        return value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&#39;");
    }

    private record MathInfo(TeXIcon icon, boolean display) {}

    private final class MathEditorKit extends HTMLEditorKit {
        private final ViewFactory ordinary = new HTMLFactory();
        private final ViewFactory views = element -> {
            if(element.getAttributes().getAttribute(javax.swing.text.StyleConstants.NameAttribute)==HTML.Tag.CONTENT&&StudyEmoji.matches(element))
                return StudyEmoji.view(element);
            if(element.getAttributes().getAttribute(javax.swing.text.StyleConstants.NameAttribute)==HTML.Tag.PRE)
                return StudyCodeBlock.view(element);
            if(StudyCodeBlock.insideCode(element)) {
                Object kind=element.getAttributes().getAttribute(javax.swing.text.StyleConstants.NameAttribute);
                if(kind==HTML.Tag.IMPLIED || kind==HTML.Tag.P)return StudyCodeBlock.line(element);
                if(kind==HTML.Tag.CONTENT)return StudyCodeBlock.token(element);
            }
            if(element.getAttributes().getAttribute(javax.swing.text.StyleConstants.NameAttribute)==HTML.Tag.CONTENT
                    &&element.getAttributes().getAttribute(HTML.Tag.CODE) instanceof AttributeSet)
                return new StudyInlineCode(element);
            if (element.getAttributes().getAttribute(HTML.Tag.SPAN) instanceof AttributeSet span) {
                Object id = span.getAttribute(HTML.Attribute.ID);
                if (id != null) {
                    MathInfo info;
                    synchronized (MATH_CACHE) { info = MATH_CACHE.get(id.toString()); }
                    if (info != null) return new MathView(element, info.icon(), info.display());
                }
            }
            if(blackText && element.getAttributes().getAttribute(javax.swing.text.StyleConstants.NameAttribute)==HTML.Tag.CONTENT
                    && citationText(element))return new CitationTextView(element);
            if(readingSkin) {
                if(element.getAttributes().getAttribute(javax.swing.text.StyleConstants.NameAttribute)==HTML.Tag.CONTENT) {
                    for(Element parent=element.getParentElement();parent!=null;parent=parent.getParentElement())
                        if(java.util.Set.of("h1","h2","h3","h4").contains(parent.getName()))return new HeadingTextView(element);
                }
                View decorated=SummarySkin.view(element);
                if(decorated!=null)return decorated;
            }
            return ordinary.create(element);
        };

        @Override public ViewFactory getViewFactory() { return views; }
        @Override public javax.swing.text.Document createDefaultDocument() {
            if(!readingSkin&&!blackText)return super.createDefaultDocument();
            var styles=new javax.swing.text.html.StyleSheet() {
                @Override public Color getForeground(AttributeSet attributes) {
                    return blackText?Color.BLACK:super.getForeground(attributes);
                }
                @Override public java.awt.Font getFont(AttributeSet attributes) {
                    java.awt.Font css=super.getFont(attributes);
                    if(!readingSkin)return css;
                    if(css.getFamily().equalsIgnoreCase(java.awt.Font.MONOSPACED))return css;
                    java.awt.Font font=css.isBold()
                        ?dev.synesis.poc.ui.MistWorkspaceTheme.font(java.awt.Font.BOLD,css.getSize())
                        :dev.synesis.poc.ui.LibraryDesign.font(java.awt.Font.PLAIN,css.getSize());
                    return css.isItalic()?font.deriveFont(css.getStyle(),css.getSize2D()):font;
                }
            };
            styles.addStyleSheet(getStyleSheet());
            var document=new javax.swing.text.html.HTMLDocument(styles);
            document.setParser(getParser());document.setAsynchronousLoadPriority(4);document.setTokenThreshold(100);
            return document;
        }
    }

    private static boolean citationText(Element element) {
        Object link=element.getAttributes().getAttribute(HTML.Tag.A);
        if(link instanceof AttributeSet attrs && String.valueOf(attrs.getAttribute(HTML.Attribute.HREF)).startsWith("page:"))return true;
        for(Element parent=element;parent!=null;parent=parent.getParentElement()) {
            if("muted".equals(String.valueOf(parent.getAttributes().getAttribute(HTML.Attribute.CLASS)))) {
                try {
                    int start=parent.getStartOffset(),length=Math.min(8,parent.getEndOffset()-start);
                    if(parent.getDocument().getText(start,length).stripLeading().startsWith("근거"))return true;
                } catch(javax.swing.text.BadLocationException ignored) { }
            }
        }
        return false;
    }
    private static final class CitationTextView extends javax.swing.text.html.InlineView {
        CitationTextView(Element element){super(element);}
        @Override public Color getForeground(){return new Color(0x4d4d4d);}
    }

    private static final class HeadingTextView extends javax.swing.text.html.InlineView {
        HeadingTextView(Element element){super(element);}
        @Override public java.awt.Font getFont(){
            return dev.synesis.poc.ui.LibraryDesign.font(java.awt.Font.BOLD,super.getFont().getSize());
        }
    }

    /** Formula text remains in the Swing document, so a dragged range can be copied. */
    private static final class MathView extends GlyphView {
        private final TeXIcon icon;
        private final int leadingGap;

        MathView(Element element, TeXIcon icon, boolean display) {
            super(element);
            this.icon = icon;
            this.leadingGap = display ? 2 : 10;
        }

        @Override public float getPreferredSpan(int axis) {
            return axis == View.X_AXIS ? icon.getIconWidth() + leadingGap + 2 : icon.getIconHeight() + 2;
        }

        @Override public float getMinimumSpan(int axis) { return getPreferredSpan(axis); }
        @Override public float getMaximumSpan(int axis) { return getPreferredSpan(axis); }
        @Override public float getTabbedSpan(float x, TabExpander expander) {
            return getPreferredSpan(View.X_AXIS);
        }
        @Override public float getPartialSpan(int from, int to) {
            int chars=Math.max(1,getEndOffset()-getStartOffset());
            int selected=Math.max(0,Math.min(to,getEndOffset())-Math.max(from,getStartOffset()));
            return getPreferredSpan(View.X_AXIS)*selected/chars;
        }
        @Override public float getAlignment(int axis) {
            return axis == View.Y_AXIS ? icon.getBaseLine() : .5f;
        }
        @Override public int getBreakWeight(int axis, float pos, float len) { return BadBreakWeight; }
        @Override public View breakView(int axis, int offset, float pos, float len) { return this; }
        @Override public int getNextVisualPositionFrom(int position,Position.Bias bias,Shape allocation,
                                                       int direction,Position.Bias[] nextBias)
                throws javax.swing.text.BadLocationException {
            // Vector painting never initializes GlyphView's ordinary text painter.
            // Swing still consults it while hit-testing between adjacent views.
            checkPainter();
            return super.getNextVisualPositionFrom(position,bias,allocation,direction,nextBias);
        }

        @Override public void paint(Graphics graphics, Shape allocation) {
            Rectangle box = allocation.getBounds();
            Graphics2D vector = (Graphics2D) graphics.create();
            try {
                vector.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                vector.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,
                    RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
                icon.paintIcon(getContainer(), vector, box.x + leadingGap, box.y);
                if (getContainer() instanceof JEditorPane pane) {
                    int from = Math.max(getStartOffset(), pane.getSelectionStart());
                    int to = Math.min(getEndOffset(), pane.getSelectionEnd());
                    if (from < to) {
                        int chars = Math.max(1, getEndOffset() - getStartOffset());
                        int left = box.x + leadingGap + Math.round(icon.getIconWidth()
                            * (from - getStartOffset()) / (float) chars);
                        int right = box.x + leadingGap + Math.round(icon.getIconWidth()
                            * (to - getStartOffset()) / (float) chars);
                        vector.setComposite(AlphaComposite.SrcOver.derive(.35f));
                        vector.setColor(pane.getSelectionColor());
                        vector.fillRect(left, box.y, Math.max(1, right - left), icon.getIconHeight());
                    }
                }
            } finally { vector.dispose(); }
        }

        @Override public Shape modelToView(int position, Shape allocation, Position.Bias bias) {
            Rectangle box = allocation.getBounds();
            int chars = Math.max(1, getEndOffset() - getStartOffset());
            int index = Math.max(0, Math.min(chars, position - getStartOffset()));
            return new Rectangle(box.x + leadingGap + Math.round(icon.getIconWidth() * index / (float) chars),
                box.y, 1, icon.getIconHeight() + 2);
        }

        @Override public int viewToModel(float x, float y, Shape allocation, Position.Bias[] bias) {
            Rectangle box = allocation.getBounds();
            int chars = Math.max(1, getEndOffset() - getStartOffset());
            int index = Math.round((x - box.x - leadingGap) * chars / Math.max(1f, icon.getIconWidth()));
            bias[0] = Position.Bias.Forward;
            return Math.max(getStartOffset(), Math.min(getEndOffset(), getStartOffset() + index));
        }
    }
}
