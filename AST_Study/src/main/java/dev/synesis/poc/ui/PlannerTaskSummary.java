package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;

/** Compact per-day task counts with a delayed, bounded hover list. */
final class PlannerTaskSummary extends JButton {
    static final Color DONE=new Color(0x1428d1),PENDING=new Color(0xd50b16);
    final PlannerDesign planner;final LocalDate date;final List<Task> tasks;
    PlannerPopover popup;
    final Timer opening=new Timer(160,e->showTasks()),closing=new Timer(180,e->closeTasks());
    private final MouseAdapter hover=new MouseAdapter(){
        @Override public void mouseEntered(MouseEvent e){closing.stop();if(popup==null)opening.restart();}
        @Override public void mouseExited(MouseEvent e){opening.stop();closing.restart();}
    };
    PlannerTaskSummary(PlannerDesign planner,LocalDate date,List<Task> tasks){
        this.planner=planner;this.date=date;this.tasks=List.copyOf(tasks);opening.setRepeats(false);closing.setRepeats(false);
        setUI(new javax.swing.plaf.basic.BasicButtonUI());setOpaque(false);setContentAreaFilled(false);setBorder(null);setFocusPainted(false);setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        long done=tasks.stream().filter(Task::completed).count();name(this,date+" 할 일 · 완료 "+done+"개, 미완료 "+(tasks.size()-done)+"개");
        addMouseListener(hover);addActionListener(e->{if(popup==null)showTasks();else closeTasks();});
        addHierarchyListener(e->{if((e.getChangeFlags()&(HierarchyEvent.PARENT_CHANGED|HierarchyEvent.SHOWING_CHANGED))!=0&&!isShowing())closeTasks();});
    }
    @Override protected void paintComponent(Graphics graphics){
        Graphics2D g=quality(graphics);List<Task> shown=tasks.stream().sorted(java.util.Comparator.comparing(Task::completed)).limit(2).toList();
        int barHeight=getHeight()<38?6:8,gap=3,y=4;
        for(Task task:shown){g.setColor(task.completed()?DONE:PENDING);g.fillRoundRect(0,y,getWidth()+4,barHeight,4,4);y+=barHeight+gap;}
        if(tasks.size()>=2){g.setColor(NAVY);int dot=2,spacing=Math.max(3,Math.min(7,getWidth()/3)),cx=getWidth()/2;y+=3;for(int i=-1;i<=1;i++)g.fillOval(cx+i*spacing-1,y,dot,dot);}
        g.dispose();
    }
    JPanel taskList(){
        Card content=new Card(Color.WHITE,12);content.putClientProperty("planner.dropReveal",true);content.setLayout(new BorderLayout(0,10));content.setBorder(BorderFactory.createEmptyBorder(14,14,14,14));
        content.add(heading(date.format(DateTimeFormatter.ofPattern("M월 d일"))+" · 할 일 "+tasks.size()+"개",14),BorderLayout.NORTH);
        JPanel rows=new JPanel();rows.setOpaque(false);rows.setLayout(new BoxLayout(rows,BoxLayout.Y_AXIS));
        for(Task task:tasks){
            JButton row=button((task.completed()?"✓  ":"!  ")+task.title(),false,()->{closeTasks();SwingUtilities.invokeLater(()->planner.editTask(task));});row.setHorizontalAlignment(SwingConstants.LEFT);row.setForeground(task.completed()?DONE:PENDING);row.setToolTipText((task.completed()?"완료 · ":"미완료 · ")+task.title());row.setMaximumSize(new Dimension(Integer.MAX_VALUE,34));row.setPreferredSize(new Dimension(246,34));rows.add(row);rows.add(Box.createVerticalStrut(6));
        }
        JScrollPane scroll=scroll(rows);scroll.setPreferredSize(new Dimension(246,Math.min(240,tasks.size()*40)));content.add(scroll);content.add(label("할 일을 누르면 상세 내용을 수정할 수 있어요.",11,BLUE_MUTED),BorderLayout.SOUTH);
        content.setPreferredSize(new Dimension(280,content.getPreferredSize().height));return content;
    }
    void showTasks(){opening.stop();closing.stop();if(popup!=null||SwingUtilities.getRootPane(this)==null)return;
        JPanel list=taskList();watchHover(list);popup=new PlannerPopover(this,list,()->{popup=null;closing.stop();});popup.showList();
    }
    private void watchHover(Component component){component.addMouseListener(new MouseAdapter(){@Override public void mouseEntered(MouseEvent e){closing.stop();}@Override public void mouseExited(MouseEvent e){closing.restart();}});if(component instanceof Container container)for(Component child:container.getComponents())watchHover(child);}
    void closeTasks(){opening.stop();closing.stop();if(popup!=null)popup.close();}
    @Override public void removeNotify(){closeTasks();super.removeNotify();}
}
