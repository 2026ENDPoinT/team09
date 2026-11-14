package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.text.JTextComponent;
import java.awt.*;
import java.util.ArrayList;
import java.util.List;

/** Transient content anchors captured once per split gesture; no timers or image copies. */
final class ResizeScrollAnchor {
    private record Entry(JViewport viewport,Component view,Component target,double fraction,int textOffset,int x) {}
    private final List<Entry> entries=new ArrayList<>();
    ResizeScrollAnchor(Container root){captureComponent(root);}
    private void capture(Container root) {
        for(Component child:root.getComponents())captureComponent(child);
    }
    private void captureComponent(Component child) {
            if(child instanceof JScrollPane scroll && !Boolean.TRUE.equals(scroll.getClientProperty("synesis.resizeOwnAnchor"))) {
                JViewport viewport=scroll.getViewport();Component view=viewport.getView();
                if(view==null || !scroll.isVisible())return;
                Point p=viewport.getViewPosition();int x=Math.min(Math.max(0,view.getWidth()-1),p.x+Math.max(1,viewport.getWidth()/2));
                Component target=view instanceof Container c?SwingUtilities.getDeepestComponentAt(c,x,p.y+2):view;
                if(target==null)target=view;
                Point local=SwingUtilities.convertPoint(view,new Point(x,p.y),target);
                int offset=target instanceof JTextComponent text?text.viewToModel2D(local):-1;
                entries.add(new Entry(viewport,view,target,local.y/(double)Math.max(1,target.getHeight()),offset,p.x));
            } else if(child instanceof Container nested)capture(nested);
    }
    void restore() {
        for(Entry entry:entries) {
            if(entry.viewport.getView()!=entry.view || !SwingUtilities.isDescendingFrom(entry.target,entry.view)&&entry.target!=entry.view)continue;
            int y=(int)Math.round(entry.fraction*entry.target.getHeight());
            if(entry.textOffset>=0 && entry.target instanceof JTextComponent text)try {
                var box=text.modelToView2D(Math.min(entry.textOffset,text.getDocument().getLength()));if(box!=null)y=(int)box.getY();
            }catch(javax.swing.text.BadLocationException ignored){}
            Point at=SwingUtilities.convertPoint(entry.target,0,y,entry.view);
            entry.viewport.setViewPosition(new Point(Math.max(0,Math.min(entry.x,entry.view.getWidth()-entry.viewport.getWidth())),
                Math.max(0,Math.min(at.y,entry.view.getHeight()-entry.viewport.getHeight()))));
        }
    }
}
