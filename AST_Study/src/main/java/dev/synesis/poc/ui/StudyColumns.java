package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseEvent;
import java.util.List;
import java.util.*;
import java.util.function.Consumer;

/** Two stable physical slots, with one retained component per learning feature. EDT only. */
public final class StudyColumns extends JPanel {
    private final Map<String,JComponent> views=new LinkedHashMap<>();
    private final Map<String,String> labels=new LinkedHashMap<>();
    private final Map<String,ResizeScrollAnchor> bookmarks=new HashMap<>();
    private final String[] selected=new String[2];
    private final LayoutMotionPanel[] slots={new LayoutMotionPanel(new BorderLayout()),new LayoutMotionPanel(new BorderLayout())};
    private final JSplitPane split=new ProportionalSplitPane(JSplitPane.HORIZONTAL_SPLIT);
    private final JButton add=new MenuButton("학습창 추가 ＋",null);
    private Consumer<Integer> countChanged=count->{};
    private Consumer<String> selectionChanged=name->{};
    private Runnable beforeLayout=()->{};
    private javax.swing.Timer transition,exchange;
    private List<LayoutMotionPanel> held=List.of();
    private double ratio=.5;
    private int lastUsedSlot;

    public StudyColumns() {
        super(new BorderLayout());setOpaque(false);
        split.setBorder(null);split.setBackground(StudyTheme.CANVAS);split.setContinuousLayout(true);
        split.setResizeWeight(.5);split.setDividerSize(0);
        for(LayoutMotionPanel slot:slots){slot.setBorder(BorderFactory.createEmptyBorder(1,1,1,1));slot.setMinimumSize(new Dimension(0,0));slot.setMotionBudget(60,90,524_288);}
        add(new JLayer<>(split,new SplitDividerHitLayer()),BorderLayout.CENTER);
        MistWorkspaceTheme.button(add,false);
        add.addActionListener(e->menu(add,-1));
    }
    public void configure(Consumer<Integer> countChanged,Consumer<String> selectionChanged,Runnable beforeLayout){
        this.countChanged=countChanged;this.selectionChanged=selectionChanged;this.beforeLayout=beforeLayout;
    }
    public JButton addButton(){return add;}
    public void register(String key,String label,JComponent view){views.put(key,view);if(label!=null)labels.put(key,label);}
    public JButton selector(String key,String label) {
        JButton button=new MenuButton(label,new Icon(){
            public int getIconWidth(){return 12;}
            public int getIconHeight(){return 12;}
            public void paintIcon(Component c,Graphics graphics,int x,int y){
                Graphics2D g=(Graphics2D)graphics.create();
                try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(c.getForeground());g.setStroke(new BasicStroke(1.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                    g.drawLine(x+2,y+4,x+6,y+8);g.drawLine(x+6,y+8,x+10,y+4);
                }finally{g.dispose();}
            }
        });
        button.setHorizontalAlignment(SwingConstants.LEFT);button.setHorizontalTextPosition(SwingConstants.LEFT);button.setIconTextGap(8);
        button.setFont(MistWorkspaceTheme.font(Font.BOLD,18));button.setForeground(MistWorkspaceTheme.INK);
        button.setOpaque(false);button.setContentAreaFilled(false);button.setBorder(BorderFactory.createEmptyBorder(2,0,2,4));
        button.setFocusPainted(true);button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        button.putClientProperty("synesis.preserveFont",true);button.putClientProperty("synesis.preserveButton",true);
        button.setToolTipText("이 창에서 볼 학습 내용 선택");
        button.addActionListener(e->menu(button,indexOf(key)));
        return button;
    }
    private void menu(JButton owner,int slot) {
        for(MenuElement element:MenuSelectionManager.defaultManager().getSelectedPath()){
            if(element instanceof ViewMenu current&&current.getInvoker()==owner&&current.isVisible()){
                current.setVisible(false);
                return;
            }
        }
        if(slot<0&&count()==2)return;
        JPopupMenu menu=new ViewMenu();
        for(var entry:labels.entrySet()) {
            String key=entry.getKey();int other=indexOf(key);
            if(slot<0&&other>=0)continue;
            String suffix=slot>=0&&Objects.equals(selected[slot],key)?"  ✓":other>=0?"  ⇄":"";
            JMenuItem item=new JMenuItem(entry.getValue()+suffix);
            item.setFont(MistWorkspaceTheme.font(Font.PLAIN,14));
            item.setBorder(BorderFactory.createEmptyBorder(9,14,9,14));
            if(other>=0&&other!=slot)item.setToolTipText("다른 창과 내용을 서로 바꿔요");
            item.addActionListener(e->{if(slot<0)open(key);else select(slot,key);});menu.add(item);
        }
        menu.show(owner,0,owner.getHeight());
    }
    public int count(){return (selected[0]==null?0:1)+(selected[1]==null?0:1);}
    public boolean containsView(String key){return indexOf(key)>=0;}
    private int indexOf(String key){for(int i=0;i<2;i++)if(Objects.equals(selected[i],key))return i;return -1;}
    public void openFromNavigation(String key){
        int existing=indexOf(key);
        if(existing>=0){lastUsedSlot=existing;selectionChanged.accept(key);return;}
        if(count()<2)open(key);
        else select(lastUsedSlot,key);
    }
    public void noteInteraction(Component component){
        for(int i=0;i<2;i++)if(selected[i]!=null&&SwingUtilities.isDescendingFrom(component,slots[i])){
            if(lastUsedSlot!=i){lastUsedSlot=i;selectionChanged.accept(selected[i]);}
            return;
        }
    }
    /** Programmatic navigation reveals an already open feature instead of moving it. */
    public void showView(String key){
        if(!views.containsKey(key))return;
        if(containsView(key)){selectionChanged.accept(key);return;}
        if(count()==0)open(key);else select(selected[0]!=null?0:1,key);
    }
    public void open(String key){
        if(!views.containsKey(key)||containsView(key)||count()==2)return;
        finishExchange();stopTransition();beforeLayout.run();
        int old=count(),slot=selected[0]==null?0:1;
        selected[slot]=key;lastUsedSlot=slot;mount();selectionChanged.accept(key);updateAdd();
        if(old==0){applySplit();countChanged.accept(1);return;}
        int width=Math.max(0,split.getWidth()-4);
        split.setLeftComponent(slots[0]);split.setRightComponent(slots[1]);split.setDividerSize(4);
        split.setDividerLocation(slot==1?width:0);
        transition=SplitPaneTransition.animate(split,(int)(width*ratio),180,()->{},()->{transition=null;applySplit();});
        countChanged.accept(2);
    }
    public void select(int slot,String key){
        if(slot<0||slot>1||selected[slot]==null||!views.containsKey(key)||Objects.equals(selected[slot],key))return;
        finishExchange();stopTransition();rememberRatio();
        int other=indexOf(key);String previous=selected[slot];
        for(String name:selected)if(name!=null)bookmarks.put(name,new ResizeScrollAnchor(views.get(name)));
        // Freeze only changed slots; one commit prevents transient duplication during a swap.
        List<LayoutMotionPanel> affected=other>=0?List.of(slots[slot],slots[other]):List.of(slots[slot]);
        if(isShowing()&&!LayoutMotionPanel.isImmediateLayout()) {
            ArrayList<LayoutMotionPanel> frozen=new ArrayList<>();
            for(LayoutMotionPanel panel:affected)frozen.addAll(LayoutMotionPanel.holdTree(panel));held=frozen;
        }
        selected[slot]=key;lastUsedSlot=slot;if(other>=0)selected[other]=previous;
        selectionChanged.accept(key);
        if(held.isEmpty()){mount();restoreBookmarks();return;}
        exchange=new javax.swing.Timer(slots[slot].fadeOutMillis(),e->finishExchange());
        exchange.setRepeats(false);exchange.start();
    }
    public void closeView(String key){
        int slot=indexOf(key);if(slot<0)return;
        finishExchange();stopTransition();beforeLayout.run();rememberRatio();
        bookmarks.put(key,new ResizeScrollAnchor(views.get(key)));
        selected[slot]=null;updateAdd();
        if(count()==0){countChanged.accept(0);return;} // Outer PDF split animates the final closing shell.
        countChanged.accept(1);
        int target=slot==0?0:Math.max(0,split.getWidth()-4);
        transition=SplitPaneTransition.animate(split,target,180,()->{},()->{transition=null;mount();applySplit();});
    }
    private void rememberRatio(){if(count()==2&&split.getWidth()>4)ratio=Math.max(.15,Math.min(.85,split.getDividerLocation()/(double)(split.getWidth()-4)));}
    private void updateAdd(){add.setVisible(count()<2);add.setText(count()==0?"학습창 추가 ＋":"함께 보기 ＋");}
    private void mount(){
        // Detach first: adding B to A must not remove B after it has already moved.
        boolean[] changed=new boolean[2];
        for(int i=0;i<2;i++){
            JComponent desired=views.get(selected[i]);
            changed[i]=slots[i].getComponentCount()!=(desired==null?0:1)||desired!=null&&desired.getParent()!=slots[i];
            if(changed[i])slots[i].removeAll();
        }
        for(int i=0;i<2;i++)if(changed[i]){
            if(selected[i]!=null){JComponent view=views.get(selected[i]);slots[i].add(view,BorderLayout.CENTER);view.setVisible(true);}
            slots[i].revalidate();slots[i].repaint();
        }
    }
    private void restoreBookmarks(){
        SwingUtilities.invokeLater(()->{for(String key:selected)if(key!=null&&bookmarks.containsKey(key))bookmarks.get(key).restore();});
    }
    private void applySplit(){
        split.setLeftComponent(selected[0]!=null?slots[0]:null);split.setRightComponent(selected[1]!=null?slots[1]:null);
        split.setDividerSize(count()==2?4:0);split.revalidate();
        if(count()==2)split.setDividerLocation((int)(Math.max(0,split.getWidth()-4)*ratio));
        restoreBookmarks();
    }
    private void finishExchange(){
        if(exchange==null&&held.isEmpty())return;
        if(exchange!=null){exchange.stop();exchange=null;}
        mount();List<LayoutMotionPanel> release=held;held=List.of();LayoutMotionPanel.releaseTree(release);restoreBookmarks();
    }
    private void stopTransition(){if(transition!=null){transition.stop();transition=null;applySplit();}}
    public void dispose(){finishExchange();stopTransition();}
    @Override public void removeNotify(){finishExchange();stopTransition();super.removeNotify();}

    private static final class MenuButton extends JButton {
        private MouseEvent dismissingPress;

        MenuButton(String label,Icon icon){super(label,icon);}

        @Override protected void processMouseEvent(MouseEvent event){
            if(event.getID()==MouseEvent.MOUSE_PRESSED){
                boolean dismissed=event==dismissingPress;
                dismissingPress=null;
                if(dismissed)return;
            }
            super.processMouseEvent(event);
        }
    }

    /** Reveal a fixed-size lightweight menu without repeatedly laying out its items. */
    private static final class ViewMenu extends JPopupMenu {
        private float progress=1;
        private long started;
        private final javax.swing.Timer reveal=new javax.swing.Timer(16,e->{
            progress=Math.min(1,(System.nanoTime()-started)/140_000_000f);
            repaint();if(progress>=1)((javax.swing.Timer)e.getSource()).stop();
        });
        @Override public void setVisible(boolean visible){
            if(reveal==null){super.setVisible(visible);return;}
            // Swing can dismiss the popup on mouse-down, before the button handles that press.
            if(!visible&&isVisible()&&getInvoker() instanceof MenuButton button
                    &&EventQueue.getCurrentEvent() instanceof MouseEvent press
                    &&press.getID()==MouseEvent.MOUSE_PRESSED&&press.getComponent()==button
                    &&SwingUtilities.isLeftMouseButton(press)){
                button.dismissingPress=press;
            }
            reveal.stop();progress=visible&&!Boolean.getBoolean("synesis.reduceMotion")?0:1;
            super.setVisible(visible);
            if(visible&&progress==0){started=System.nanoTime();reveal.start();}
        }
        @Override public void paint(Graphics graphics){
            if(progress>=1){super.paint(graphics);return;}
            Graphics2D g=(Graphics2D)graphics.create();
            try{float eased=progress*progress*(3-2*progress);g.clipRect(0,0,getWidth(),Math.round(getHeight()*eased));super.paint(g);}finally{g.dispose();}
        }
        @Override public void removeNotify(){reveal.stop();super.removeNotify();}
    }
}
