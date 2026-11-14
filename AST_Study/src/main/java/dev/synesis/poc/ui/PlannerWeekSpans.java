package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.event.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;

/** Transparent, independently scrollable bars floating over the top of the hourly grid. */
final class PlannerWeekSpans extends UnifiedScrollPane {
    static final int MAX_ROWS=4,ROW_HEIGHT=32,PADDING=6;
    private static final String SCROLL_POSITION="planner.weekSpanScroll";
    private static final DateTimeFormatter DATE=DateTimeFormatter.ofPattern("M/d");
    record Span(Occurrence occurrence,int firstDay,int lastDay,int row) {}
    private record ScrollPosition(LocalDate week,int y) {}
    final PlannerDesign planner;
    final LocalDate monday;
    final Map<JButton,Span> spans=new LinkedHashMap<>();
    final SpanBody body;
    final int rows;
    private boolean positioned,adjusting;

    static boolean includes(Occurrence occurrence){
        return occurrence.event().allDay()||!occurrence.start().toLocalDate().equals(occurrence.end().minusNanos(1).toLocalDate());
    }
    PlannerWeekSpans(PlannerDesign planner,JViewport viewport){
        super(VERTICAL_SCROLLBAR_AS_NEEDED,HORIZONTAL_SCROLLBAR_NEVER);
        this.planner=planner;monday=weekStart(planner.anchor);
        List<Integer> occupied=new ArrayList<>();
        List<Occurrence> events=occurrences(planner.state,monday,monday.plusDays(7)).stream().filter(PlannerWeekSpans::includes)
            .sorted(Comparator.comparingInt(this::firstDay).thenComparing(Comparator.comparingInt(this::lastDay).reversed())
                .thenComparing(Occurrence::start).thenComparing(Occurrence::key)).toList();
        for(Occurrence occurrence:events){
            int first=firstDay(occurrence),last=lastDay(occurrence),mask=((1<<(last-first+1))-1)<<first,row=0;
            while(row<occupied.size()&&(occupied.get(row)&mask)!=0)row++;
            if(row==occupied.size())occupied.add(mask);else occupied.set(row,occupied.get(row)|mask);
            spans.put(bar(occurrence),new Span(occurrence,first,last,row));
        }
        rows=occupied.size();body=new SpanBody();setViewport(viewport);setViewportView(body);
        setOpaque(false);setViewportBorder(BorderFactory.createEmptyBorder(PADDING,0,PADDING,0));setBorder(null);
        viewport.setOpaque(false);
        setLayout(new PlannerOverlayScrollLayout(){@Override public void layoutContainer(Container parent){
            super.layoutContainer(parent);
            viewport.doLayout();body.doLayout();
            if(!positioned&&viewport.getExtentSize().height>0){
                Object saved=planner.calendar.getClientProperty(SCROLL_POSITION);
                int y=saved instanceof ScrollPosition position&&position.week().equals(monday)?position.y():0;
                adjusting=true;
                try{viewport.setViewPosition(new Point(0,Math.max(0,Math.min(y,body.getHeight()-viewport.getHeight()))));}
                finally{adjusting=false;}
                positioned=true;
                if(SwingUtilities.isDescendingFrom(PlannerWeekSpans.this,planner.calendar))
                    planner.calendar.putClientProperty(SCROLL_POSITION,new ScrollPosition(monday,viewport.getViewPosition().y));
            }
        }});
        JScrollBar bar=getVerticalScrollBar();bar.setPreferredSize(new Dimension(8,1));bar.setBorder(null);
        bar.setUI(new FadingScrollBarUI(new Color(0x7a8ca3),.28f));setComponentZOrder(bar,0);bar.setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        viewport.addChangeListener(e->{
            if(positioned&&!adjusting&&SwingUtilities.isDescendingFrom(this,planner.calendar))
                planner.calendar.putClientProperty(SCROLL_POSITION,new ScrollPosition(monday,viewport.getViewPosition().y));
        });
        name(this,"종일 및 연속 일정 · 최대 4줄 · 별도 스크롤");
    }
    int visibleHeight(){return rows==0?0:PADDING*2+Math.min(MAX_ROWS,rows)*ROW_HEIGHT;}
    int coveredHeight(int day){
        Rectangle visible=getViewport().getViewRect();int covered=0;
        for(var entry:spans.entrySet()){
            Span span=entry.getValue();Rectangle b=entry.getKey().getBounds();
            if(day>=span.firstDay()&&day<=span.lastDay()&&b.intersects(visible))
                covered=Math.max(covered,Math.min(visible.height,b.y+b.height-visible.y+3));
        }
        return covered==0?0:getViewport().getY()+covered;
    }
    // Empty space belongs to the hourly grid, including its click-to-add action.
    @Override public boolean contains(int x,int y){
        if(!super.contains(x,y))return false;
        JScrollBar scroll=getVerticalScrollBar();
        if(scroll.isVisible()&&scroll.getBounds().contains(x,y))return true;
        JViewport view=getViewport();
        if(!view.getBounds().contains(x,y))return false;
        Point p=SwingUtilities.convertPoint(this,new Point(x,y),body);
        return spans.keySet().stream().anyMatch(button->button.getBounds().contains(p));
    }
    @Override public boolean isOptimizedDrawingEnabled(){return false;}
    @Override public Dimension getPreferredSize(){return new Dimension(1,visibleHeight());}
    private int firstDay(Occurrence occurrence){return Math.max(0,(int)ChronoUnit.DAYS.between(monday,occurrence.start().toLocalDate()));}
    private int lastDay(Occurrence occurrence){return Math.min(6,(int)ChronoUnit.DAYS.between(monday,occurrence.end().minusNanos(1).toLocalDate()));}

    private JButton bar(Occurrence occurrence){
        LocalDate first=occurrence.start().toLocalDate(),last=occurrence.end().minusNanos(1).toLocalDate();
        String text=occurrence.event().title()+(first.equals(last)?"":" ("+first.format(DATE)+" – "+last.format(DATE)+")");
        Color fill=new Color(occurrence.event().color().rgb);
        JButton button=new JButton(text){@Override protected void paintComponent(Graphics graphics){
            Graphics2D g=quality(graphics);
            PlannerEventCard.surface(g,0,0,getWidth()-1,getHeight()-2,fill,4);g.dispose();
            super.paintComponent(graphics);
        }};
        button.setUI(new BasicButtonUI());button.setOpaque(false);button.setContentAreaFilled(false);button.setFocusPainted(false);
        button.setBorder(BorderFactory.createEmptyBorder(0,10,2,8));button.setFont(medium(11));button.setForeground(PlannerEventCard.foreground(PlannerEventCard.background(fill)));
        button.setHorizontalAlignment(SwingConstants.LEFT);button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        name(button,occurrence.event().title()+" · "+occurrence.start()+" ~ "+occurrence.end());button.setToolTipText(button.getName());
        button.addActionListener(e->planner.editEvent(occurrence.event(),occurrence.start()));
        button.addFocusListener(new FocusAdapter(){@Override public void focusGained(FocusEvent e){button.scrollRectToVisible(new Rectangle(0,0,button.getWidth(),button.getHeight()));}});
        return button;
    }

    final class SpanBody extends JPanel implements Scrollable {
        SpanBody(){super(null);setOpaque(false);spans.keySet().forEach(this::add);}
        Shape fadeArea(boolean above,int edge){
            Rectangle visible=getViewport().getViewRect();java.awt.geom.Area area=new java.awt.geom.Area();
            for(JButton button:spans.keySet()){
                Rectangle b=button.getBounds();
                if(above?b.y<visible.y+edge:b.y+b.height>visible.y+visible.height-edge)
                    area.add(new java.awt.geom.Area(new Rectangle(b.x-4,0,b.width+8,visible.height)));
            }
            return area;
        }
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);Graphics2D g=quality(graphics);
            for(JButton button:spans.keySet()){
                Rectangle b=button.getBounds();
                if(!g.hitClip(b.x-5,b.y-2,b.width+10,b.height+10))continue;
                for(int spread=4;spread>=1;spread--){
                    g.setColor(new Color(15,35,55,3*(5-spread)));
                    g.fillRoundRect(b.x-spread,b.y+3-spread/2,b.width-1+spread*2,b.height-2+spread,8+spread*2,8+spread*2);
                }
            }
            g.dispose();
        }
        @Override public Dimension getPreferredSize(){return new Dimension(1,rows*ROW_HEIGHT);}
        @Override public Dimension getPreferredScrollableViewportSize(){return new Dimension(1,visibleHeight());}
        @Override public int getScrollableUnitIncrement(Rectangle r,int orientation,int direction){return ROW_HEIGHT;}
        @Override public int getScrollableBlockIncrement(Rectangle r,int orientation,int direction){return Math.max(ROW_HEIGHT,r.height-ROW_HEIGHT);}
        @Override public boolean getScrollableTracksViewportWidth(){return true;}
        @Override public boolean getScrollableTracksViewportHeight(){return false;}
        @Override public void doLayout(){
            for(var entry:spans.entrySet()){
                Span span=entry.getValue();int x=PlannerCalendar.dayX(getWidth(),span.firstDay())+4;
                int right=PlannerCalendar.dayX(getWidth(),span.lastDay()+1)-4;
                entry.getKey().setBounds(x,2+span.row()*ROW_HEIGHT,Math.max(1,right-x),ROW_HEIGHT-4);
            }
        }
    }
}
