package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import dev.synesis.poc.ui.RoundedPopupMenuUI;
import java.awt.*;
import java.awt.event.*;
import javax.swing.*;
import javax.swing.plaf.basic.BasicTreeUI;
import javax.swing.tree.*;

/** Shared study TOC: quiet branch guides, with blue text only at the reading position. */
final class SummaryOutlineTree extends JTree {
    private static final Color GUIDE=new Color(0xCCD8E6);
    private String currentId="";
    private int hovered=-1;
    SummaryOutlineTree() {
        setRootVisible(false);setShowsRootHandles(false);setRowHeight(29);
        putClientProperty("JTree.lineStyle","Angled");
        setBackground(Color.WHITE);setBorder(BorderFactory.createEmptyBorder(3,3,3,3));
        setFont(MistWorkspaceTheme.font(Font.PLAIN,13));
        setCellRenderer(new DefaultTreeCellRenderer(){
            private boolean over;
            @Override public Component getTreeCellRendererComponent(JTree tree,Object value,boolean selected,boolean expanded,boolean leaf,int row,boolean focus) {
                super.getTreeCellRendererComponent(tree,value,false,expanded,leaf,row,false);
                Object item=((DefaultMutableTreeNode)value).getUserObject();
                boolean active=false;
                if(item instanceof SummaryOutline.Entry entry) {setText(entry.title());active=entry.id().equals(currentId);setToolTipText(entry.title()+(entry.page()>0?" · p."+entry.page():""));}
                over=row==hovered;setIcon(null);setOpaque(false);setBorder(BorderFactory.createEmptyBorder(3,5,3,8));
                setFont(MistWorkspaceTheme.font(Font.PLAIN,13));setForeground(active?new Color(0x2383e2):new Color(0x73726e));
                setBackgroundNonSelectionColor(new Color(0,0,0,0));return this;
            }
            @Override public void paint(Graphics g) {
                if(over){Graphics2D c=(Graphics2D)g.create();c.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);c.setColor(new Color(0xf1f1ef));c.fillRoundRect(0,0,getWidth(),getHeight(),6,6);c.dispose();}
                super.paint(g);
            }
        });
        addMouseMotionListener(new MouseMotionAdapter(){@Override public void mouseMoved(MouseEvent e){hoverRow(getRowForLocation(e.getX(),e.getY()));}});
        addMouseListener(new MouseAdapter(){@Override public void mouseExited(MouseEvent e){hoverRow(-1);}});
    }
    @Override public void updateUI(){setUI(new BranchUI());}
    @Override protected void paintComponent(Graphics graphics) {
        super.paintComponent(graphics);
        Rectangle clip = graphics.getClipBounds();
        if (clip == null || getRowCount() < 2) return;
        int first = getClosestRowForLocation(clip.x, clip.y);
        int last = getClosestRowForLocation(clip.x, clip.y + clip.height - 1);
        Graphics lines = graphics.create();
        try {
            lines.setColor(RoundedPopupMenuUI.DIVIDER);
            for (int row = first; row >= 0 && row <= last && row + 1 < getRowCount(); row++) {
                Rectangle bounds = getRowBounds(row);
                if (bounds != null) {
                    int y = bounds.y + bounds.height - 1;
                    lines.drawLine(4, y, getWidth() - 5, y);
                }
            }
        } finally {
            lines.dispose();
        }
    }
    /** Reuse JTree's clipped layout cache; no separate traversal, images or paint timer. */
    private static final class BranchUI extends BasicTreeUI {
        @Override protected void installDefaults(){
            super.installDefaults();
            setExpandedIcon(null);setCollapsedIcon(null);setLeftChildIndent(8);setRightChildIndent(8);
            setHashColor(GUIDE);
        }
        @Override protected void paintHorizontalLine(Graphics g,JComponent c,int y,int left,int right){
            g.setColor(GUIDE);g.drawLine(left,y,right,y);
        }
        @Override protected void paintVerticalLine(Graphics g,JComponent c,int x,int top,int bottom){
            g.setColor(GUIDE);g.drawLine(x,top,x,bottom);
        }
    }
    void current(String id) {if(!currentId.equals(id)){currentId=id;repaint();}}
    private void hoverRow(int row) {
        if(hovered==row)return;int old=hovered;hovered=row;
        Rectangle before=getRowBounds(old),after=getRowBounds(row);if(before!=null)repaint(before);if(after!=null)repaint(after);
    }
}
