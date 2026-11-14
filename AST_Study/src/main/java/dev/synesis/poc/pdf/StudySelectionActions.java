package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.awt.*;
import java.awt.datatransfer.StringSelection;
import java.awt.event.*;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Set;
import java.util.Collections;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.BiConsumer;
import javax.swing.*;
import javax.swing.text.DefaultEditorKit;

/** Selection across cached prose/formula panes; no polling, TeX parsing, or model calls on drag. */
final class StudySelectionActions implements AutoCloseable {
    private final Container root;
    private final Consumer<String> ask,notice;
    private final BooleanSupplier canAsk;
    private final List<StudyHtmlPane> panes=new ArrayList<>();
    private record Binding(MouseAdapter listener,Action copy) {}
    private final Map<StudyHtmlPane,Binding> bindings=new IdentityHashMap<>();
    private final Set<JComponent> surfaces=Collections.newSetFromMap(new IdentityHashMap<>());
    private StudyHtmlPane anchor;
    private Component pressOwner;
    private Point pressed;
    private int anchorOffset;
    private long anchorRevision,gesture;
    private boolean dragged;
    private JPopupMenu popup;
    private String contextTab;
    private Map<String,StudySelectionContext.Source> sources=Map.of();
    private BiConsumer<String,JsonObject> contextualAsk;
    private final MouseAdapter gestures=new MouseAdapter() {
        @Override public void mousePressed(MouseEvent event) {
            if(event.isPopupTrigger()){show(event.getComponent(),event);return;}
            if(!SwingUtilities.isLeftMouseButton(event))return;
            gesture++;dismiss();resetGesture();StudyHtmlPane.clearStudySelections();
            pressed=point(event.getComponent(),event.getPoint());
            anchor=event.getComponent() instanceof StudyHtmlPane pane?pane:hitPane(pressed);
            if(anchor==null)return;
            pressOwner=event.getComponent();anchorRevision=anchor.contentRevision();
            anchorOffset=offset(anchor,pressed);anchor.setStudySelection(anchorOffset,anchorOffset);
            anchor.requestFocusInWindow();
            if(event.getClickCount()>1) {
                try {
                    int start=event.getClickCount()==2?javax.swing.text.Utilities.getWordStart(anchor,anchorOffset)
                        :javax.swing.text.Utilities.getParagraphElement(anchor,anchorOffset).getStartOffset();
                    int end=event.getClickCount()==2?javax.swing.text.Utilities.getWordEnd(anchor,anchorOffset)
                        :javax.swing.text.Utilities.getParagraphElement(anchor,anchorOffset).getEndOffset();
                    anchor.setStudySelection(start,end);
                }catch(javax.swing.text.BadLocationException ignored){}
            }
        }
        @Override public void mouseDragged(MouseEvent event) {
            if(!validAnchor()||event.getComponent()!=pressOwner
                ||(event.getModifiersEx()&InputEvent.BUTTON1_DOWN_MASK)==0)return;
            if(pressed.distance(point(pressOwner,event.getPoint()))<3&&!dragged)return;
            dragged=true;extend(pressOwner,event.getPoint());
        }
        @Override public void mouseReleased(MouseEvent event) {
            if(event.isPopupTrigger()){show(event.getComponent(),event);resetGesture();return;}
            if(!SwingUtilities.isLeftMouseButton(event))return;
            try {
                if(event.getComponent()==pressOwner&&dragged&&validAnchor()) {
                    extend(pressOwner,event.getPoint());show(pressOwner,event);
                }
            }finally {resetGesture();}
        }
    };

    StudySelectionActions(Container root,Consumer<String> ask,BooleanSupplier canAsk,Consumer<String> notice) {
        this.root=root;this.ask=ask;this.canAsk=canAsk;this.notice=notice;
    }
    void setContext(String tab,Map<String,StudySelectionContext.Source> sources,BiConsumer<String,JsonObject> ask) {
        contextTab=tab;this.sources=sources;contextualAsk=ask;
    }
    void refresh() {
        panes.clear();bindSurface(root);visit(root);
        for(StudyHtmlPane old:new ArrayList<>(bindings.keySet()))if(!panes.contains(old))detach(old);
        for(JComponent old:new ArrayList<>(surfaces))
            if(old!=root&&(!root.isAncestorOf(old)||panes.stream().noneMatch(old::isAncestorOf)))unbindSurface(old);
        if(anchor!=null&&!validAnchor())resetGesture();
    }
    private void visit(Container container) {
        for(Component child:container.getComponents()) {
            if(child instanceof StudyHtmlPane pane) {
                panes.add(pane);
                if(pane.getClientProperty(StudySelectionActions.class)==this)continue;
                pane.putClientProperty(StudySelectionActions.class,this);
                pane.addMouseListener(gestures);pane.addMouseMotionListener(gestures);
                pane.setStudySelection(pane.getSelectionStart(),pane.getSelectionEnd());
                bindings.put(pane,new Binding(gestures,pane.getActionMap().get(DefaultEditorKit.copyAction)));
                pane.getActionMap().put(DefaultEditorKit.copyAction,new AbstractAction(){
                    @Override public void actionPerformed(ActionEvent event){copy(selectedMarkdown());}
                });
            } else if(child instanceof Container nested){
                int before=panes.size();visit(nested);if(panes.size()>before)bindSurface(nested);
            }
        }
    }
    private void bindSurface(Container container) {
        if(!(container instanceof JPanel||container instanceof JViewport||container instanceof JScrollPane))return;
        JComponent surface=(JComponent)container;
        if(!surfaces.add(surface))return;
        surface.putClientProperty(StudySelectionActions.class,this);
        surface.addMouseListener(gestures);surface.addMouseMotionListener(gestures);
    }
    private void unbindSurface(JComponent surface) {
        surface.removeMouseListener(gestures);surface.removeMouseMotionListener(gestures);
        surface.putClientProperty(StudySelectionActions.class,null);surfaces.remove(surface);
    }
    private void resetGesture(){anchor=null;pressOwner=null;pressed=null;anchorOffset=0;anchorRevision=0;dragged=false;}
    private Point point(Component pane,Point point){return SwingUtilities.convertPoint(pane,point,root);}
    private boolean validAnchor() {
        return anchor!=null&&root.isAncestorOf(anchor)&&anchor.contentRevision()==anchorRevision;
    }
    private List<StudyHtmlPane> orderedPanes() {
        return panes.stream().filter(this::visible).sorted(Comparator
            .comparingInt((StudyHtmlPane p)->point(p,new Point()).y)
            .thenComparingInt(p->point(p,new Point()).x)).toList();
    }
    private boolean visible(StudyHtmlPane pane) {
        for(Component c=pane;c!=root;c=c.getParent())if(c==null||!c.isVisible())return false;
        return pane.getWidth()>0&&pane.getHeight()>0;
    }
    private Rectangle bounds(StudyHtmlPane pane) {
        Rectangle visible=new Rectangle(0,0,pane.getWidth(),pane.getHeight());
        visible=SwingUtilities.convertRectangle(pane,visible,root);
        for(Container parent=pane.getParent();parent!=null&&parent!=root;parent=parent.getParent())
            visible=visible.intersection(SwingUtilities.convertRectangle(parent,
                new Rectangle(0,0,parent.getWidth(),parent.getHeight()),root));
        return visible;
    }
    private StudyHtmlPane hitPane(Point destination) {
        return hitPane(destination,orderedPanes());
    }
    private StudyHtmlPane hitPane(Point destination,List<StudyHtmlPane> ordered) {
        Component hit=SwingUtilities.getDeepestComponentAt(root,destination.x,destination.y);
        if(hit instanceof StudyHtmlPane pane&&ordered.contains(pane))return pane;
        // Padding belongs to its formula/document container until the pointer actually leaves it.
        Container owner=hit instanceof Container c?c:hit==null?root:hit.getParent();
        while(owner!=null&&owner!=root) {
            Container candidate=owner;
            if(ordered.stream().anyMatch(candidate::isAncestorOf))break;
            owner=owner.getParent();
        }
        StudyHtmlPane nearest=null;double closest=Double.MAX_VALUE;
        for(StudyHtmlPane pane:ordered) {
            if(owner!=null&&owner!=root&&!owner.isAncestorOf(pane))continue;
            Rectangle box=bounds(pane);if(box.isEmpty())continue;
            double dx=Math.max(0,Math.max(box.x-destination.x,destination.x-box.getMaxX()));
            double dy=Math.max(0,Math.max(box.y-destination.y,destination.y-box.getMaxY()));
            double distance=dy*dy+dx*dx;
            if(distance<closest){closest=distance;nearest=pane;}
        }
        return nearest;
    }
    private int offset(StudyHtmlPane pane,Point destination) {
        Point local=SwingUtilities.convertPoint(root,destination,pane);
        return Math.max(0,Math.min(pane.getDocument().getLength(),pane.viewToModel2D(local)));
    }
    void extend(Component source,Point location) {
        if(!validAnchor())return;
        Point destination=point(source,location);
        List<StudyHtmlPane> ordered=orderedPanes();
        StudyHtmlPane endPane=hitPane(destination,ordered);
        if(endPane==null)return;
        int first=ordered.indexOf(anchor),last=ordered.indexOf(endPane);
        if(first<0)return;
        int endOffset=offset(endPane,destination);
        for(int i=0;i<ordered.size();i++) {
            StudyHtmlPane pane=ordered.get(i);int start=0,end=0;
            if(i>=Math.min(first,last)&&i<=Math.max(first,last)) {
                end=pane.getDocument().getLength();
                if(first==last){start=anchorOffset;end=endOffset;}
                else if(first<last){if(i==first)start=anchorOffset;if(i==last)end=endOffset;}
                else {start=i==first?anchorOffset:end;end=i==last?endOffset:0;}
            }
            pane.setStudySelection(start,end);
        }
        // Scroll the shared document only at the outer viewport edge. Individual
        // formula carets must never pull their own viewport or the document around.
        if(root instanceof JComponent document) {
            Rectangle visible=document.getVisibleRect();
            if(visible.height>0&&(destination.y<visible.y||destination.y>=visible.getMaxY()))
                document.scrollRectToVisible(new Rectangle(visible.x,destination.y,1,1));
        }
    }
    String selectedMarkdown() {
        StringBuilder text=new StringBuilder();
        for(StudyHtmlPane pane:orderedPanes()) {
            if(pane.getSelectionStart()==pane.getSelectionEnd())continue;
            String part=pane.selectionMarkdown(pane.getSelectionStart(),pane.getSelectionEnd());
            if(part==null||part.isBlank())continue;
            if(!text.isEmpty())text.append("\n\n");text.append(part);
        }
        return text.toString();
    }
    private void show(Component pane,MouseEvent event) {
        String selection=selectedMarkdown();if(selection.isBlank())return;
        JsonObject context=selectionContext(selection);
        long current=gesture;Point location=event.getPoint();
        // Let Swing's caret finish handling release before taking popup focus.
        SwingUtilities.invokeLater(()->{
            if(current!=gesture||!pane.isShowing())return;
            dismiss();popup=menu(selection,context);
            Rectangle selected=null;
            for(StudyHtmlPane part:orderedPanes()) {
                if(part.getSelectionStart()==part.getSelectionEnd() || !part.isShowing())continue;
                try {
                    java.awt.geom.Rectangle2D first=part.modelToView2D(part.getSelectionStart());
                    java.awt.geom.Rectangle2D last=part.modelToView2D(Math.max(part.getSelectionStart(),part.getSelectionEnd()-1));
                    if(first==null || last==null)continue;
                    Rectangle area=first.createUnion(last).getBounds().intersection(part.getVisibleRect());
                    if(area.isEmpty())continue;
                    Point top=area.getLocation();SwingUtilities.convertPointToScreen(top,part);area.setLocation(top);
                    if(selected==null)selected=area;else selected.add(area);
                } catch(javax.swing.text.BadLocationException ignored) { }
            }
            Point position=new Point(location);SwingUtilities.convertPointToScreen(position,pane);
            Dimension size=popup.getPreferredSize();
            if(selected!=null)position.setLocation(selected.x+(selected.width-size.width)/2,selected.y-size.height-7);
            else position.translate(-size.width/2,-size.height-7);
            GraphicsConfiguration config=pane.getGraphicsConfiguration();Rectangle screen=new Rectangle(config.getBounds());
            Insets insets=Toolkit.getDefaultToolkit().getScreenInsets(config);
            screen.x+=insets.left;screen.y+=insets.top;screen.width-=insets.left+insets.right;screen.height-=insets.top+insets.bottom;
            position.x=Math.max(screen.x,Math.min(position.x,screen.x+screen.width-size.width));
            position.y=Math.max(screen.y,Math.min(position.y,screen.y+screen.height-size.height));
            SwingUtilities.convertPointFromScreen(position,pane);popup.show(pane,position.x,position.y);
        });
    }
    JPopupMenu menu(String selection) {
        return menu(selection,selectionContext(selection));
    }
    JsonObject selectionContext(String selection) {
        return contextualAsk==null?new JsonObject():StudySelectionContext.capture(orderedPanes(),selection,contextTab,sources);
    }
    private JPopupMenu menu(String selection,JsonObject context) {
        JPopupMenu menu=new JPopupMenu();
        JMenuItem question=new JMenuItem("AI멘토에게 이 부분 질문하기");question.setEnabled(canAsk.getAsBoolean());
        question.addActionListener(event->{if(contextualAsk==null)ask.accept(selection);else contextualAsk.accept(selection,context);});menu.add(question);
        JMenuItem copy=new JMenuItem("복사");copy.addActionListener(event->copy(selection));menu.add(copy);
        return menu;
    }
    private void copy(String selection) {
        if(selection.isBlank())return;
        try {Toolkit.getDefaultToolkit().getSystemClipboard().setContents(new StringSelection(selection),null);}
        catch(IllegalStateException unavailable){notice.accept("클립보드를 잠시 사용할 수 없어요.");}
    }
    private void dismiss(){if(popup!=null){popup.setVisible(false);popup=null;}}
    private void detach(StudyHtmlPane pane) {
        Binding binding=bindings.remove(pane);if(binding==null)return;
        pane.removeMouseListener(binding.listener());pane.removeMouseMotionListener(binding.listener());
        if(binding.copy()==null)pane.getActionMap().remove(DefaultEditorKit.copyAction);
        else pane.getActionMap().put(DefaultEditorKit.copyAction,binding.copy());
        pane.putClientProperty(StudySelectionActions.class,null);
    }
    @Override public void close(){
        gesture++;dismiss();resetGesture();panes.clear();
        for(StudyHtmlPane pane:new ArrayList<>(bindings.keySet()))detach(pane);
        for(JComponent surface:new ArrayList<>(surfaces))unbindSurface(surface);
    }
}
