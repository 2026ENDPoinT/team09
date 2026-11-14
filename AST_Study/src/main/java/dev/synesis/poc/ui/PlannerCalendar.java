package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.time.*;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;
import static dev.synesis.poc.ui.PlannerDialogs.drawText;

/** Both calendars share the same occurrence source, date boundaries and edit action. */
final class PlannerCalendar extends Card {
    private static final int CORNER_RADIUS=12;
    static final String[] DAYS={"월","화","수","목","금","토","일"};final PlannerDesign planner;
    PlannerCalendar(PlannerDesign planner){super(Color.WHITE,CORNER_RADIUS);this.planner=planner;setLayout(new BorderLayout());setBorder(BorderFactory.createEmptyBorder(1,1,1,1));add(planner.monthly?new Month():new Week());}
    LocalDate today(){return LocalDate.now(planner.clock);}
    /** Figma weekly calendar: fixed day headings and a clean, scrollable time grid. */
    final class Week extends JPanel {
        final WeekBody body=new WeekBody();
        final PlannerWeekSpans spans=new PlannerWeekSpans(planner,new TimelineViewport());
        final JScrollPane timeline=new dev.synesis.poc.ui.UnifiedScrollPane(ScrollPaneConstants.VERTICAL_SCROLLBAR_ALWAYS,ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER){@Override public boolean isOptimizedDrawingEnabled(){return false;}};
        final List<JButton> edgeBadges=new ArrayList<>();
        private boolean adjusting,positioned;private int previousExtent,previousHeight,lastY;
        private IndicatorData renderedIndicators;
        private record IndicatorData(Rectangle view,int y,int bodyHeight,int gridTop,Rectangle spansView,int spansWidth,int spansHeight){}
        Week(){
            super(new BorderLayout());setOpaque(false);
            body.topInset=spans.visibleHeight();
            timeline.setViewport(new TimelineViewport());timeline.setViewportView(body);timeline.setBorder(null);timeline.setViewportBorder(null);
            timeline.getViewport().setBackground(Color.WHITE);
            timeline.setLayout(new PlannerOverlayScrollLayout(){
                @Override public void addLayoutComponent(String key,Component child){if(child instanceof JComponent c&&(c.getClientProperty("planner.edgeDay")!=null||c.getClientProperty("planner.weekSpans")!=null))return;super.addLayoutComponent(key,child);}
                @Override public void layoutContainer(Container parent){
                    boolean previous=adjusting;adjusting=true;
                    try{
                        super.layoutContainer(parent);
                        viewport.doLayout();body.doLayout();
                        Rectangle view=viewport.getBounds();
                        spans.setBounds(view.x,view.y,view.width,Math.min(view.height,spans.visibleHeight()));spans.doLayout();
                    }finally{adjusting=previous;}
                    syncViewport();updateIndicators();
                }
            });
            JScrollBar bar=timeline.getVerticalScrollBar();bar.setOpaque(false);bar.setBorder(null);bar.setPreferredSize(new Dimension(8,1));
            bar.setUI(new FadingScrollBarUI(new Color(0x7a8ca3),.28f));timeline.setComponentZOrder(bar,0);
            timeline.setColumnHeaderView(new WeekHeader());timeline.getColumnHeader().setBackground(Color.WHITE);
            name(timeline,"주간 시간표 · 1시간 단위 · 00시부터 24시까지 스크롤");add(timeline,BorderLayout.CENTER);
            if(spans.rows>0){spans.putClientProperty("planner.weekSpans",true);timeline.add(spans);timeline.setComponentZOrder(spans,0);}
            for(int day=0;day<7;day++)for(boolean above:new boolean[]{true,false}){
                final int d=day;JButton badge=new EdgeBadge(above,()->reveal(d,above));badge.putClientProperty("planner.edgeDay",day);badge.putClientProperty("planner.edgeAbove",above);
                badge.setFont(medium(10));badge.setVisible(false);edgeBadges.add(badge);timeline.add(badge);timeline.setComponentZOrder(badge,0);
            }
            timeline.getViewport().addChangeListener(e->{syncViewport();updateIndicators();});
            spans.getViewport().addChangeListener(e->updateIndicators());
        }
        // Keep the outline fixed around the visible column, above spans and scroll fades.
        @Override protected boolean isPaintingOrigin(){return true;}
        @Override public void paint(Graphics graphics){
            super.paint(graphics);
            int day=(int)java.time.temporal.ChronoUnit.DAYS.between(weekStart(planner.anchor),today());
            JViewport header=timeline.getColumnHeader(),view=timeline.getViewport();
            if(day<0||day>=7||header==null||header.getHeight()<=0||view.getHeight()<=0)return;
            Rectangle top=SwingUtilities.convertRectangle(timeline,header.getBounds(),this);
            Rectangle bottom=SwingUtilities.convertRectangle(timeline,view.getBounds(),this);
            int left=top.x+dayX(top.width,day),right=top.x+dayX(top.width,day+1);
            Graphics2D g=quality(graphics);g.setColor(PlannerWeekCalendarSkin.TODAY_OUTLINE);g.setStroke(new BasicStroke(1.5f));
            double x=left+2,y=top.y+2,w=right-left-4,h=bottom.y+bottom.height-top.y-4;
            Shape outline=new java.awt.geom.Rectangle2D.Double(x,y,w,h);
            if(day==6){
                // Only Sunday meets the calendar's rounded right edge. Keep its left corners square.
                var rounded=new java.awt.geom.Area(new java.awt.geom.RoundRectangle2D.Double(x,y,w,h,CORNER_RADIUS*2,CORNER_RADIUS*2));
                rounded.add(new java.awt.geom.Area(new java.awt.geom.Rectangle2D.Double(x,y,w/2,h)));
                outline=rounded;
            }
            g.draw(outline);
            g.dispose();
        }
        List<Position> hidden(int day,boolean above){
            JViewport view=timeline.getViewport();int top=view.getViewPosition().y+spans.coveredHeight(day),bottom=view.getViewPosition().y+view.getExtentSize().height;
            return body.positions.values().stream().filter(p->p.day()==day&&(above?body.minuteY(p.end())<=top:body.minuteY(p.start())>=bottom)).toList();
        }
        void updateIndicators(){
            if(adjusting||timeline.getViewport()==null||timeline.getViewport().getView()!=body)return;
            Rectangle view=timeline.getViewport().getBounds();
            int y=timeline.getViewport().getViewPosition().y;
            IndicatorData data=new IndicatorData(view,y,body.getHeight(),body.gridTop(),spans.getViewport().getViewRect(),spans.body.getWidth(),spans.body.getHeight());
            if(data.equals(renderedIndicators))return;renderedIndicators=data;
            int[] covers=new int[7],aboveCounts=new int[7],belowCounts=new int[7];for(int day=0;day<7;day++)covers[day]=spans.coveredHeight(day);
            for(Position position:body.positions.values()){
                int day=position.day();if(body.minuteY(position.end())<=y+covers[day])aboveCounts[day]++;
                if(body.minuteY(position.start())>=y+view.height)belowCounts[day]++;
            }
            Rectangle damage=null;
            for(JButton badge:edgeBadges){int day=(int)badge.getClientProperty("planner.edgeDay");boolean above=Boolean.TRUE.equals(badge.getClientProperty("planner.edgeAbove"));int count=above?aboveCounts[day]:belowCounts[day];
                Rectangle old=badge.isVisible()?badge.getBounds():null;
                int x=dayX(view.width,day),col=dayX(view.width,day+1)-x,w=Math.max(1,Math.min(180,col-8));
                EdgeBadge edge=(EdgeBadge)badge;boolean textChanged=edge.count!=count;
                if(textChanged){edge.count=count;badge.setText((above?"위":"아래")+"에 일정 "+count+"개가 있어요!");}
                Font font=medium(col<60?9:10);boolean fontChanged=!font.equals(badge.getFont());if(fontChanged)badge.setFont(font);
                int h=textChanged||fontChanged||badge.getWidth()!=w||badge.getHeight()==0?edge.bubbleHeight(w):badge.getHeight();
                int cover=covers[day];Rectangle bounds=new Rectangle(view.x+x+(col-w)/2,above?view.y+cover+2:view.y+view.height-h-2,w,h);
                boolean visible=count>0&&view.height-cover>=h+4,changed=textChanged||fontChanged||!bounds.equals(badge.getBounds())||visible!=badge.isVisible();
                badge.setBounds(bounds);badge.setVisible(visible);
                if(textChanged){badge.setToolTipText((above?"위":"아래")+"에 일정 "+count+"개 · 클릭해서 이동");name(badge,DAYS[day]+"요일 "+(above?"위":"아래")+"쪽 숨겨진 일정 "+count+"개");}
                if(changed){if(old!=null)damage=damage==null?old:damage.union(old);if(visible)damage=damage==null?bounds:damage.union(bounds);}
            }
            if(damage!=null)timeline.repaint(damage.x,damage.y,damage.width,damage.height);
        }
        void reveal(int day,boolean above){
            List<Position> items=hidden(day,above);if(items.isEmpty())return;
            double minute=above?items.stream().mapToDouble(Position::start).max().orElse(0):items.stream().mapToDouble(Position::start).min().orElse(1440);
            JViewport view=timeline.getViewport();int y=Math.max(0,Math.min(body.getHeight()-view.getHeight(),body.minuteY(minute)-spans.coveredHeight(day)-30));view.setViewPosition(new Point(0,y));
        }
        private void syncViewport(){
            if(adjusting||PlannerCalendar.this.getParent()==null)return;
            JViewport viewport=timeline.getViewport();int extent=viewport.getExtentSize().height,height=body.getHeight();
            if(extent<=20||body.getWidth()<=0||height!=body.getPreferredSize().height)return;
            if(!positioned||extent!=previousExtent||height!=previousHeight){
                adjusting=true;
                try{int y=body.minuteY(planner.weeklyScrollMinute);viewport.setViewPosition(new Point(0,Math.max(0,Math.min(height-extent,y))));}
                finally{adjusting=false;}
                positioned=true;previousExtent=extent;previousHeight=height;lastY=viewport.getViewPosition().y;return;
            }
            if(viewport.getViewPosition().y!=lastY){
                lastY=viewport.getViewPosition().y;double minute=(lastY-body.gridTop())*60.0/PlannerWeekCalendarSkin.HOUR_HEIGHT,quarter=Math.round(minute/15)*15;
                planner.weeklyScrollMinute=Math.abs(minute-quarter)<=30.0/PlannerWeekCalendarSkin.HOUR_HEIGHT?quarter:minute;
            }
        }
    }
    static final class EdgeBadge extends JButton {
        final boolean above;
        private int count=-1;
        EdgeBadge(boolean above,Runnable action){this.above=above;setUI(new javax.swing.plaf.basic.BasicButtonUI());setOpaque(false);setContentAreaFilled(false);setBorder(null);setFocusPainted(false);setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));addActionListener(e->action.run());}
        List<String> lines(int width){
            FontMetrics metrics=getFontMetrics(getFont());int available=Math.max(1,width-12);List<String> lines=new ArrayList<>();StringBuilder line=new StringBuilder();
            for(String word:getText().split(" ")){
                if(!line.isEmpty()&&metrics.stringWidth(line+" "+word)>available){lines.add(line.toString());line.setLength(0);}
                if(!line.isEmpty())line.append(' ');
                for(char c:word.toCharArray()){if(!line.isEmpty()&&metrics.stringWidth(line.toString()+c)>available){lines.add(line.toString());line.setLength(0);}line.append(c);}
            }
            if(!line.isEmpty())lines.add(line.toString().strip());return lines;
        }
        int bubbleHeight(int width){return lines(width).size()*14+14;}
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=quality(graphics);int tail=5,top=above?tail:0,h=getHeight()-tail;double cx=getWidth()/2.0;
            java.awt.geom.Area shape=new java.awt.geom.Area(new java.awt.geom.RoundRectangle2D.Double(.5,top+.5,getWidth()-1,h-1,9,9));
            java.awt.geom.Path2D tip=new java.awt.geom.Path2D.Double();tip.moveTo(cx-4,above?top+1:top+h-1);tip.lineTo(cx,above?.5:getHeight()-.5);tip.lineTo(cx+4,above?top+1:top+h-1);tip.closePath();shape.add(new java.awt.geom.Area(tip));
            g.setColor(Color.WHITE);g.fill(shape);g.setColor(new Color(0xaab7c6));g.draw(shape);
            List<String> lines=lines(getWidth());int y=top+(h-lines.size()*14)/2;for(String line:lines){center(g,line,getFont(),NAVY,0,y,getWidth(),14);y+=14;}g.dispose();
        }
    }
    final class TimelineViewport extends ScrollCacheViewport {
        TimelineViewport(){setCacheEnabled(true);}
        @Override protected boolean isPaintingOrigin(){return true;}
        @Override public void paint(Graphics graphics){
            super.paint(graphics);if(getView()==null||getHeight()==0)return;
            boolean floating=getView() instanceof PlannerWeekSpans.SpanBody;
            int edge=Math.max(1,floating?Math.min(28,getHeight()/4):Math.min(24,getHeight()/8)),above=getViewPosition().y,below=getViewSize().height-above-getExtentSize().height;
            Color tint=floating?Color.WHITE:new Color(244,247,252);int opacity=floating?255:210;
            Graphics2D g=quality(graphics);Color clear=new Color(tint.getRed(),tint.getGreen(),tint.getBlue(),0);
            Shape clip=g.getClip();
            if(getView() instanceof PlannerWeekSpans.SpanBody spans)g.clip(spans.fadeArea(true,edge));
            if(above>0){Color fade=new Color(tint.getRed(),tint.getGreen(),tint.getBlue(),Math.round(opacity*Math.min(1,above/(float)edge)));g.setPaint(new GradientPaint(0,0,fade,0,edge,clear));g.fillRect(0,0,getWidth(),edge);}
            g.setClip(clip);
            if(getView() instanceof PlannerWeekSpans.SpanBody spans)g.clip(spans.fadeArea(false,edge));
            if(below>0){Color fade=new Color(tint.getRed(),tint.getGreen(),tint.getBlue(),Math.round(opacity*Math.min(1,below/(float)edge)));g.setPaint(new GradientPaint(0,getHeight()-edge,clear,0,getHeight(),fade));g.fillRect(0,getHeight()-edge,getWidth(),edge);}
            g.dispose();
        }
    }
    static int gutter(int width){return PlannerWeekCalendarSkin.TIME_GUTTER;}
    static int dayX(int width,int day){return gutter(width)+(int)Math.round((width-gutter(width))*day/7.0);}
    final class WeekHeader extends JPanel {
        WeekHeader(){
            super(null);setBackground(Color.WHITE);name(this,"주간 요일과 날짜");
            for(int d=0;d<7;d++){
                LocalDate date=weekStart(planner.anchor).plusDays(d);JButton heading=dateButton(date);
                heading.putClientProperty("day",d);heading.setToolTipText(date+" · 하루 일정 보기");add(heading);
            }
        }
        int baseHeadingHeight(){return PlannerWeekCalendarSkin.HEADER_HEIGHT;}
        int headingHeight(){return baseHeadingHeight();}
        @Override public Dimension getPreferredSize(){return new Dimension(1,headingHeight());}
        @Override public void doLayout(){for(Component child:getComponents()){
            int day=(int)((JComponent)child).getClientProperty("day"),x=dayX(getWidth(),day);child.setBounds(x,0,dayX(getWidth(),day+1)-x,headingHeight());
        }}
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);Graphics2D g=quality(graphics);
            for(int d=0;d<7;d++){
                int x=dayX(getWidth(),d),width=dayX(getWidth(),d+1)-x;LocalDate date=weekStart(planner.anchor).plusDays(d);boolean now=date.equals(today());
                if(!g.hitClip(x-2,0,width+4,headingHeight()+2))continue;
                g.setColor(PlannerWeekCalendarSkin.dayBackground(d,now));g.fillRect(x,0,width,headingHeight());
                PlannerWeekCalendarSkin.centerLine(g,PlannerWeekCalendarSkin.DAYS[d],medium(9),d>=5?PlannerWeekCalendarSkin.WEEKEND:MUTED,x,4,width,16);
                if(now){
                    int dayLeft=Math.round((width-new java.awt.font.TextLayout(PlannerWeekCalendarSkin.DAYS[d],medium(9),g.getFontRenderContext()).getAdvance())/2);
                    PlannerWeekCalendarSkin.centerLine(g,"오늘",medium(10),NAVY,x,4,dayLeft,16);
                }
                PlannerWeekCalendarSkin.centerLine(g,Integer.toString(date.getDayOfMonth()),bold(16),now?NAVY:INK,x,20,width,24);
                if(d>0){g.setColor(PlannerWeekCalendarSkin.DAY_LINE);g.fill(new java.awt.geom.Rectangle2D.Double(x,0,1.5,headingHeight()));}
            }
            // The header boundary stays visible even when all-day bars precede the time grid.
            g.setColor(BORDER);g.fillRect(0,headingHeight()-1,getWidth(),1);
            g.dispose();
        }
    }
    record Position(int day,int lane,int lanes,double start,double end) {}
    final class WeekBody extends JPanel implements Scrollable {
        int topInset;
        final Map<JButton,Position> positions=new LinkedHashMap<>();
        WeekBody(){super(null);setBackground(Color.WHITE);name(this,"주간 시간표, 1시간 단위로 00시부터 24시까지 스크롤");LocalDate monday=weekStart(planner.anchor);List<Occurrence> events=occurrences(planner.state,monday,monday.plusDays(7)).stream().filter(o->!o.event().allDay()).toList();
            for(int d=0;d<7;d++){LocalDate date=monday.plusDays(d);List<Occurrence> day=events.stream().filter(o->o.on(date)).toList();List<Occurrence> cluster=new ArrayList<>();LocalDateTime end=null;for(Occurrence o:day){if(end!=null&&!o.start().isBefore(end)){cluster(cluster,date,d);cluster.clear();end=null;}cluster.add(o);if(end==null||o.end().isAfter(end))end=o.end();}cluster(cluster,date,d);}
            addMouseListener(new MouseAdapter(){public void mouseClicked(MouseEvent e){LocalDateTime time=timeAt(e.getPoint());if(time!=null)planner.editEvent(null,time);}});
        }
        void cluster(List<Occurrence> cluster,LocalDate date,int day){
            List<LocalDateTime> ends=new ArrayList<>();
            Map<Occurrence,Integer> lanes=new LinkedHashMap<>();
            for(Occurrence occurrence:cluster){
                int lane=0;
                while(lane<ends.size()&&ends.get(lane).isAfter(occurrence.start()))lane++;
                if(lane==ends.size())ends.add(occurrence.end());
                else ends.set(lane,occurrence.end());
                lanes.put(occurrence,lane);
            }
            LocalDateTime dayStart=date.atStartOfDay(),dayEnd=dayStart.plusDays(1);
            for(var entry:lanes.entrySet()){
                Occurrence occurrence=entry.getKey();
                LocalDateTime start=occurrence.start().isBefore(dayStart)?dayStart:occurrence.start();
                LocalDateTime end=occurrence.end().isAfter(dayEnd)?dayEnd:occurrence.end();
                JButton button=planner.eventButton(new Occurrence(occurrence.event(),start,end),false);
                positions.put(button,new Position(day,entry.getValue(),ends.size(),
                    Duration.between(dayStart,start).toMinutes(),Duration.between(dayStart,end).toMinutes()));
                add(button);
            }
        }
        int gridTop(){return topInset;}
        int gridBottom(){return Math.max(1,getHeight());}
        int minuteY(double minute){return gridTop()+(int)Math.round((gridBottom()-gridTop())*minute/1440.0);}
        @Override public Dimension getPreferredSize(){return new Dimension(1,gridTop()+PlannerWeekCalendarSkin.HOUR_HEIGHT*24);}
        @Override public Dimension getPreferredScrollableViewportSize(){return new Dimension(1,452);}
        @Override public int getScrollableUnitIncrement(Rectangle r,int orientation,int direction){return Math.max(1,(gridBottom()-gridTop())/96);}
        @Override public int getScrollableBlockIncrement(Rectangle r,int orientation,int direction){return Math.max(1,r.height-(gridBottom()-gridTop())/24);}
        @Override public boolean getScrollableTracksViewportWidth(){return true;}
        @Override public boolean getScrollableTracksViewportHeight(){return false;}
        LocalDateTime timeAt(Point point){
            int gutter=gutter(getWidth());if(point.x<gutter||point.x>=getWidth()||point.y<gridTop())return null;
            int day=Math.max(0,Math.min(6,(int)((point.x-gutter)*7.0/(getWidth()-gutter))));
            int minute=(int)Math.floor((point.y-gridTop())*1440.0/(gridBottom()-gridTop())/15)*15;
            minute=Math.max(0,Math.min(1425,minute));return weekStart(planner.anchor).plusDays(day).atStartOfDay().plusMinutes(minute);
        }
        @Override public void doLayout(){
            for(var e:positions.entrySet()){
                Position p=e.getValue();int x=dayX(getWidth(),p.day),w=dayX(getWidth(),p.day+1)-x,inset=6;
                double lane=Math.max(1,w-inset*2)/(double)p.lanes;int start=minuteY(p.start),end=minuteY(p.end),gap=end-start>=8?2:0;
                int y=Math.min(gridBottom()-2,start+gap),height=Math.max(2,Math.min(gridBottom()-y,end-y-gap));
                e.getKey().setBounds(x+inset+(int)Math.round(p.lane*lane),y,Math.max(1,(int)Math.floor(lane)-(p.lanes>1?2:0)),height);
            }
        }
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);Graphics2D g=quality(graphics);int gutter=gutter(getWidth());
            for(int d=0;d<7;d++){
                int x=dayX(getWidth(),d),width=dayX(getWidth(),d+1)-x;
                g.setColor(PlannerWeekCalendarSkin.dayBackground(d,weekStart(planner.anchor).plusDays(d).equals(today())));g.fillRect(x,0,width,getHeight());
                g.setColor(d==0?BORDER:PlannerWeekCalendarSkin.DAY_LINE);g.fill(new java.awt.geom.Rectangle2D.Double(x,0,d==0?1:1.5,getHeight()));
            }
            for(int hour=0;hour<24;hour++){
                int y=minuteY(hour*60);if(!g.hitClip(0,y-2,getWidth(),21))continue;g.setColor(BORDER);g.fillRect(gutter,y,getWidth()-gutter,1);
                PlannerWeekCalendarSkin.line(g,String.format("%02d:00",hour),regular(9),MUTED,5,y+3,gutter-7,14);
            }
            g.dispose();
        }
    }
    final class Month extends JPanel {
        final LocalDate first=weekStart(planner.anchor.withDayOfMonth(1));
        final int rows=(int)Math.ceil((planner.anchor.withDayOfMonth(1).getDayOfWeek().getValue()-1+planner.anchor.lengthOfMonth())/7.0);
        record Span(Occurrence occurrence,int row,int firstDay,int lastDay,int lane){}
        final Map<JButton,int[]> cells=new LinkedHashMap<>();final Map<Integer,List<Occurrence>> items=new HashMap<>();
        final Map<JButton,Span> spans=new LinkedHashMap<>();final Map<Integer,JButton> moreButtons=new HashMap<>();final Map<Integer,Integer> hiddenCounts=new HashMap<>();
        final int[] laneCounts=new int[rows];
        Month(){
            super(null);setBackground(Color.WHITE);name(this,"월간 달력");List<Occurrence> events=occurrences(planner.state,first,first.plusDays(rows*7L));
            for(int i=0;i<rows*7;i++){
                LocalDate day=first.plusDays(i);List<Occurrence> dayEvents=events.stream().filter(o->o.on(day)).toList();items.put(i,dayEvents);
                JButton heading=dateButton(day);heading.setToolTipText(day+" · 일정 "+dayEvents.size()+"개");cells.put(heading,new int[]{i,-1});add(heading);
                if(!dayEvents.isEmpty()){JButton more=new MonthMore(()->planner.dayEvents(day));cells.put(more,new int[]{i,2});moreButtons.put(i,more);add(more);}
            }
            for(int week=0;week<rows;week++){
                LocalDate weekStart=first.plusDays(week*7L);List<Integer> occupied=new ArrayList<>();
                List<Occurrence> ordered=events.stream().filter(o->o.start().isBefore(weekStart.plusDays(7).atStartOfDay())&&o.end().isAfter(weekStart.atStartOfDay()))
                    .sorted(Comparator.comparing((Occurrence o)->!multiDay(o)).thenComparing(Occurrence::start).thenComparing(o->o.event().id())).toList();
                for(Occurrence occurrence:ordered){
                    int start=0,end=6;while(!occurrence.on(weekStart.plusDays(start)))start++;while(!occurrence.on(weekStart.plusDays(end)))end--;
                    int mask=((1<<(end-start+1))-1)<<start,lane=0;while(lane<occupied.size()&&(occupied.get(lane)&mask)!=0)lane++;
                    if(lane==occupied.size())occupied.add(mask);else occupied.set(lane,occupied.get(lane)|mask);
                    Span span=new Span(occurrence,week,start,end,lane);JButton button=multiDay(occurrence)?spanButton(span):planner.eventButton(occurrence,true);spans.put(button,span);add(button);
                }
                laneCounts[week]=occupied.size();
            }
            addMouseListener(new MouseAdapter(){public void mouseClicked(MouseEvent e){if(e.getY()<headingHeight()||getWidth()<=0||getHeight()<=headingHeight())return;int col=Math.min(6,e.getX()*7/getWidth()),row=Math.min(rows-1,(e.getY()-headingHeight())*rows/Math.max(1,getHeight()-headingHeight()));planner.monthlyView.selectDate(first.plusDays(row*7L+col));}});
        }
        boolean multiDay(Occurrence occurrence){return !occurrence.start().toLocalDate().equals(occurrence.end().minusNanos(1).toLocalDate());}
        JButton spanButton(Span span){
            Occurrence occurrence=span.occurrence();LocalDate left=first.plusDays(span.row()*7L+span.firstDay()),right=first.plusDays(span.row()*7L+span.lastDay()+1);
            boolean before=occurrence.start().isBefore(left.atStartOfDay()),after=occurrence.end().isAfter(right.atStartOfDay());
            JButton button=new JButton(){@Override protected void paintComponent(Graphics graphics){
                Graphics2D g=quality(graphics);Color color=new Color(occurrence.event().color().rgb);
                PlannerEventCard.surface(g,before?-5:0,0,getWidth()+(before?5:0)+(after?5:0),getHeight(),color,4);
                LocalDate end=occurrence.end().minusNanos(1).toLocalDate();String text=occurrence.event().title()+" · "+occurrence.start().format(java.time.format.DateTimeFormatter.ofPattern("M/d"))+" – "+end.format(java.time.format.DateTimeFormatter.ofPattern("M/d"));
                PlannerWeekCalendarSkin.line(g,text,medium(11),PlannerMonthView.INK,before?6:10,0,getWidth()-(before?12:16),getHeight());g.dispose();
            }};
            button.setUI(new javax.swing.plaf.basic.BasicButtonUI());button.setOpaque(false);button.setContentAreaFilled(false);button.setBorder(null);button.setFocusPainted(false);button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
            name(button,occurrence.event().title()+" · "+occurrence.start()+" ~ "+occurrence.end());button.setToolTipText(button.getName());button.addActionListener(e->planner.editEvent(occurrence.event(),occurrence.start()));return button;
        }
        int headingHeight(){return PlannerMonthView.HEADER_HEIGHT;}
        double rowHeight(){return Math.max(1,(getHeight()-headingHeight())/(double)rows);}
        int dateHeight(){return PlannerMonthView.DAY_HEADING;}
        int eventHeight(){return PlannerMonthView.EVENT_HEIGHT;}
        void repaintDate(LocalDate date){
            int i=(int)java.time.temporal.ChronoUnit.DAYS.between(first,date);if(i<0||i>=rows*7)return;
            double col=getWidth()/7.0,row=rowHeight();int x=(int)Math.round(i%7*col),y=(int)Math.round(headingHeight()+i/7*row);
            repaint(x-2,y-2,(int)Math.ceil(col)+4,(int)Math.ceil(row)+4);
        }
        int capacity(){return Math.max(0,Math.min(3,(int)((rowHeight()-dateHeight()-3)/(eventHeight()+3))));}
        @Override public void doLayout(){
            double col=getWidth()/7.0,row=rowHeight();int capacity=capacity();int[] visible=new int[rows*7];
            for(var entry:spans.entrySet()){
                Span span=entry.getValue();JButton button=entry.getKey();int slots=laneCounts[span.row()]>capacity?Math.max(0,capacity-1):capacity;
                boolean show=span.lane()<slots;button.setVisible(show);if(!show)continue;
                int x=(int)Math.round(span.firstDay()*col)+6,right=(int)Math.round((span.lastDay()+1)*col)-6,y=(int)Math.round(headingHeight()+span.row()*row)+dateHeight()+span.lane()*(eventHeight()+3);
                button.setBounds(x,y,Math.max(1,right-x),eventHeight());for(int day=span.firstDay();day<=span.lastDay();day++)visible[span.row()*7+day]++;
            }
            hiddenCounts.clear();
            for(var entry:cells.entrySet()){
                int[] cell=entry.getValue();int i=cell[0],x=(int)Math.round(i%7*col),y=(int)Math.round(headingHeight()+i/7*row),w=(int)Math.round((i%7+1)*col)-x;JButton button=entry.getKey();
                if(cell[1]<0){button.setBounds(x+2,y+2,Math.max(1,w-4),Math.max(1,dateHeight()-2));continue;}
                int hidden=items.get(i).size()-visible[i];hiddenCounts.put(i,hidden);button.setVisible(hidden>0);button.setText("+ "+hidden+"개 일정");button.setToolTipText(first.plusDays(i)+" · 숨겨진 일정 "+hidden+"개 모두 보기");
                int slots=laneCounts[i/7]>capacity?Math.max(0,capacity-1):capacity;
                int h=capacity==0?Math.max(1,Math.min(14,(int)row-dateHeight()-2)):eventHeight();
                button.setBounds(x+4,y+dateHeight()+slots*(eventHeight()+3),Math.max(1,w-8),h);
            }
        }
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);Graphics2D g=quality(graphics);double col=getWidth()/7.0,row=rowHeight();int header=headingHeight();
            for(int d=0;d<7;d++){
                int x=(int)Math.round(d*col),w=(int)Math.round((d+1)*col)-x;
                if(!g.hitClip(x-2,0,w+4,header+2))continue;
                if(d>=5){g.setColor(PlannerMonthView.WEEKEND_BG);g.fillRect(x,0,w,header);}
                PlannerWeekCalendarSkin.centerLine(g,PlannerWeekCalendarSkin.DAYS[d],medium(10),d>=5?WEEKEND:PlannerMonthView.MUTED,x,0,w,header);
                g.setColor(BORDER);g.drawLine(x,0,x,header);
            }
            for(int i=0;i<rows*7;i++){
                LocalDate date=first.plusDays(i);int x=(int)Math.round(i%7*col),y=(int)Math.round(header+i/7*row),w=(int)Math.round((i%7+1)*col)-x;boolean now=date.equals(today()),outside=!YearMonth.from(date).equals(YearMonth.from(planner.anchor));
                int height=(int)Math.round(header+(i/7+1)*row)-y;
                g.setColor(outside?SURFACE:now?SURFACE:i%7>=5?PlannerMonthView.WEEKEND_BG:Color.WHITE);g.fillRect(x,y,w,height);
                g.setColor(BORDER);g.drawLine(x,y,x,getHeight());g.drawLine(x,y,x+w,y);
                // Preserve the original overlapping grid strokes at fractional
                // scales; skip only offscreen content, not those long strokes.
                if(!g.hitClip(x-2,y-2,w+4,height+4))continue;
                if(date.equals(planner.monthlyView.selectedDate)){g.setColor(new Color(0x8eacd0));g.drawRect(x,y,w-1,height-1);}
                int diameter=22,top=6;
                if(now){g.setColor(NAVY);g.fillOval(x+6,y+top,diameter,diameter);}
                PlannerWeekCalendarSkin.centerLine(g,Integer.toString(date.getDayOfMonth()),medium(12),now?Color.WHITE:outside?PlannerMonthView.SUBTLE:i%7>=5?WEEKEND:PlannerMonthView.INK,x+6,y+top,diameter,diameter);
                if(now&&w>70)PlannerWeekCalendarSkin.line(g,"오늘",medium(9),NAVY,x+w-26,y+8,24,18);
                
            }
            g.dispose();
        }
    }
    static final class MonthMore extends JButton {
        MonthMore(Runnable action){setUI(new javax.swing.plaf.basic.BasicButtonUI());setOpaque(false);setContentAreaFilled(false);setBorder(null);setFocusPainted(false);setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));addActionListener(e->action.run());}
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=quality(graphics);if(getModel().isRollover()){g.setColor(SURFACE);g.fillRoundRect(0,0,getWidth(),getHeight(),6,6);}
            g.setFont(medium(getHeight()<18?9:12));FontMetrics metrics=g.getFontMetrics();double scale=Math.min(1,Math.max(1,getWidth()-4)/(double)Math.max(1,metrics.stringWidth(getText())));
            g.translate(2,0);g.scale(scale,1);g.setColor(NAVY);g.drawString(getText(),0,(getHeight()-metrics.getHeight())/2+metrics.getAscent());g.dispose();
        }
    }
    JButton dateButton(LocalDate date){JButton b=new JButton();b.setUI(new javax.swing.plaf.basic.BasicButtonUI());b.setContentAreaFilled(false);b.setFocusPainted(false);b.setBorder(null);name(b,date+" 일정과 할 일 보기");b.setToolTipText("일정과 할 일 보기");b.addActionListener(e->{if(planner.monthly)planner.monthlyView.selectDate(date);else planner.dayEvents(date);});return b;}
    static void center(Graphics2D g,String text,Font font,Color color,int x,int y,int width,int height){g.setFont(font);FontMetrics m=g.getFontMetrics();g.setColor(color);g.drawString(text,x+(width-m.stringWidth(text))/2,y+(height-m.getHeight())/2+m.getAscent());}
}
