package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.event.*;
import java.awt.font.TextLayout;
import java.time.format.DateTimeFormatter;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;

/** Calendar geometry from MAIN-플래너_주간v / 4:299; event surfaces share the editor preview renderer. */
final class PlannerWeekCalendarSkin {
    static final int TIME_GUTTER=44,HEADER_HEIGHT=48,HOUR_HEIGHT=48;
    static final String[] DAYS={"MON","TUE","WED","THU","FRI","SAT","SUN"};
    static final Color DAY_LINE=new Color(0xdae9ff),WEEKEND=new Color(0xd00e0e);
    static final Color WEEKEND_BACKGROUND=new Color(0xfffafa),TODAY_OUTLINE=new Color(0xa3b3c7);
    private PlannerWeekCalendarSkin() {}

    static Color dayBackground(int day,boolean today){
        return day>=5?WEEKEND_BACKGROUND:today?SURFACE:Color.WHITE;
    }

    static void line(Graphics2D g,String text,Font font,Color color,int x,int y,int width,int height){
        if(text.isBlank()||width<=0||height<=0||!g.hitClip(x-1,y-1,width+2,height+2))return;Graphics2D clipped=(Graphics2D)g.create();
        clipped.clipRect(x,y,width,height);TextLayout layout=PlannerTextLayout.get(clipped,text,font);
        clipped.setColor(color);layout.draw(clipped,x,y+(height-layout.getAscent()-layout.getDescent())/2+layout.getAscent());clipped.dispose();
    }
    static void centerLine(Graphics2D g,String text,Font font,Color color,int x,int y,int width,int height){
        TextLayout layout=PlannerTextLayout.get(g,text,font);int offset=Math.round((width-layout.getAdvance())/2);
        line(g,text,font,color,x+offset,y,Math.max(1,width-offset),height);
    }
    static JButton eventButton(Occurrence occurrence,boolean compact,State state,Runnable edit){
        var event=occurrence.event();
        DateTimeFormatter clock=DateTimeFormatter.ofPattern("HH:mm");
        String end=occurrence.end().equals(occurrence.start().toLocalDate().plusDays(1).atStartOfDay())
            ?"24:00":occurrence.end().format(clock);
        String time=event.allDay()?"종일":occurrence.start().format(clock)+"–"+end;
        var tags=event.tagIds().stream().map(state::tagName).filter(name->!name.isBlank()).toList();
        Color accent=new Color(event.color().rgb);JButton button=new JButton();button.setUI(new BasicButtonUI(){
            @Override public void paint(Graphics graphics,JComponent component){
                Graphics2D g=quality(graphics);int w=component.getWidth(),h=component.getHeight();
                PlannerEventCard.paint(g,0,0,w,h,event.title(),time,accent,tags);
                g.dispose();
            }
        });
        button.setBorder(null);button.setOpaque(false);button.setContentAreaFilled(false);button.setFocusPainted(false);
        button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));name(button,event.title()+" "+occurrence.start()+" ~ "+occurrence.end());
        button.setToolTipText(event.title()+" · "+occurrence.start()+" ~ "+occurrence.end());button.addActionListener(e->edit.run());
        button.addFocusListener(new FocusAdapter(){@Override public void focusGained(FocusEvent e){button.scrollRectToVisible(new Rectangle(0,0,button.getWidth(),button.getHeight()));}});
        return button;
    }
}
