package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import java.util.List;
import java.util.*;
import java.util.function.Supplier;
import javax.swing.*;
import javax.swing.tree.*;

/** Concept headings and leaves share the summary TOC's sizing, hover and dismissal behavior. */
final class ConceptOutlineNavigation implements AutoCloseable {
    record Item(String title,int depth,JComponent target) {}
    final JButton button=new JButton("목차");
    private final SummaryOutlinePopup popup=new SummaryOutlinePopup();
    private final SummaryOutlineTree tree=new SummaryOutlineTree();
    private final SummaryOutlineHover hover;
    private final JScrollPane host;
    private final Supplier<List<Item>> items;
    private final Map<String,JComponent> targets=new LinkedHashMap<>();

    ConceptOutlineNavigation(JScrollPane host,Supplier<List<Item>> items) {
        this.host=host;this.items=items;
        ConceptOverview.actionButton(button,66,false);button.setToolTipText("개념 목차 · 제목을 누르면 해당 내용으로 이동해요.");
        JScrollPane scroll=new dev.synesis.poc.ui.UnifiedScrollPane(tree);scroll.setBorder(null);popup.add(scroll);
        hover=new SummaryOutlineHover(host,button,popup,()->!items.get().isEmpty(),this::refresh,this::selectCurrent);
        hover.trackPopup(popup);button.addActionListener(e->hover.explicitOpen());
        tree.addMouseListener(new MouseAdapter(){@Override public void mouseClicked(MouseEvent e){if(SwingUtilities.isLeftMouseButton(e))jump(tree.getPathForLocation(e.getX(),e.getY()));}});
        tree.getInputMap().put(KeyStroke.getKeyStroke("ENTER"),"concept-outline-jump");
        tree.getActionMap().put("concept-outline-jump",new AbstractAction(){@Override public void actionPerformed(ActionEvent e){jump(tree.getSelectionPath());}});
        host.getViewport().addChangeListener(e->{if(popup.isVisible())selectCurrent();});
    }
    private void refresh() {
        DefaultMutableTreeNode root=new DefaultMutableTreeNode("목차");Map<Integer,DefaultMutableTreeNode> parents=new HashMap<>();targets.clear();
        for(Item item:items.get()) {
            String id="concept-outline-"+targets.size();targets.put(id,item.target());
            var entry=new SummaryOutline.Entry(id,"",item.title(),item.depth()+1,0,0,List.of());
            var node=new DefaultMutableTreeNode(entry);parents.getOrDefault(item.depth()-1,root).add(node);
            parents.keySet().removeIf(depth->depth>=item.depth());parents.put(item.depth(),node);
        }
        tree.setModel(new DefaultTreeModel(root));for(int row=0;row<tree.getRowCount();row++)tree.expandRow(row);
    }
    private void jump(TreePath path) {
        if(path==null||!(((DefaultMutableTreeNode)path.getLastPathComponent()).getUserObject() instanceof SummaryOutline.Entry entry))return;
        JComponent target=targets.get(entry.id());if(target==null)return;
        int y=SwingUtilities.convertPoint(target,0,0,host.getViewport().getView()).y;
        int maximum=Math.max(0,host.getViewport().getView().getHeight()-host.getViewport().getHeight());
        host.getViewport().setViewPosition(new Point(0,Math.max(0,Math.min(y,maximum))));popup.setVisible(false);
    }
    private void selectCurrent() {
        int y=host.getViewport().getViewPosition().y;String current="";
        for(var item:targets.entrySet()) {
            int at=SwingUtilities.convertPoint(item.getValue(),0,0,host.getViewport().getView()).y;
            if(current.isEmpty()||at<=y+8)current=item.getKey();else break;
        }
        tree.current(current);
    }
    void reset(){popup.close();targets.clear();}
    @Override public void close(){hover.close();}
}
