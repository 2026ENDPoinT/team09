package dev.synesis.poc.ui;

import dev.synesis.poc.planner.PlannerModel.EventColor;
import javax.swing.*;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;
import java.awt.event.*;
import java.time.*;
import java.time.format.*;
import java.util.List;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;
import static dev.synesis.poc.ui.PlannerDialogs.*;

/** MAIN-플래너_주간v / DXLkqXmL8yjdLKwg1jXQtb / 2:425. Monthly layout remains in PlannerDesign. */
final class PlannerWeekView extends JPanel {
    private static final int NAV_BUTTON_SIZE=31,NAV_ARROW_SIZE=25,NAV_TODAY_WIDTH=60,NAV_GROUP_HALF=74;
    final PlannerDesign planner;
    final Card daily=new Card(Color.WHITE,12),mini=new Card(Color.WHITE,12),todos=new Card(Color.WHITE,12),goals=new Card(Color.WHITE,12);
    final QuickNote quick=new QuickNote();
    final JPanel dailyRows=rows(),todoRows=rows(),goalRows=rows(),filters=new JPanel(new WrapLayout());
    final JScrollPane dailyScroll=quietScroll(dailyRows),todoScroll=quietScroll(todoRows),goalScroll=quietScroll(goalRows),filterScroll=quietScroll(filters);
    final JLabel day=label("",11,MUTED),range=label("",15,INK),error=label("",11,ERROR_COLOR),monthTitle=heading("",CARD_TITLE_SIZE);
    final JLabel title=heading("WEEKLY PLANNER",26),subtitle=label("주간 플래너",12,MUTED);
    final JButton previous,next,today,add,week,month,bell,previousDay,nextDay,addDaily,addTodo,addGoal;
    final JPanel switcher=new JPanel(null),dates=new JPanel(null);
    final JButton miniPrevious,miniNext,miniThisMonth;
    YearMonth miniMonth;LocalDate shownAnchor;String tagFilter="";
    private DailyData renderedDaily;
    private TodoData renderedTodos;
    private GoalData renderedGoals;
    private MiniData renderedMini;
    private record DailyData(LocalDate date,List<Task> tasks,boolean readFailed){}
    private record TodoData(LocalDate week,List<WeeklyTask> tasks,List<Tag> tags,String filter,boolean readFailed){}
    private record GoalData(LocalDate week,List<WeeklyGoal> goals,boolean readFailed){}
    private record MiniData(YearMonth month,LocalDate anchor){}

    PlannerWeekView(PlannerDesign planner){
        super(null);this.planner=planner;setBackground(Color.WHITE);name(this,"MAIN-플래너_주간v");
        previous=navigationButton("‹","이전 주",true,()->planner.navigate(-1));
        next=navigationButton("›","다음 주",true,()->planner.navigate(1));
        today=navigationButton("오늘","이번 주로 이동",false,()->{planner.anchor=LocalDate.now(planner.clock);planner.refresh();});
        add=button("+ 일정 추가",true,()->planner.editEvent(null,planner.anchor.atTime(10,0)));add.setFont(medium(14));
        week=button("주간",true,()->{});month=button("월간",false,()->planner.setMonthly(true));week.setFont(medium(11));month.setFont(medium(11));month.setBorder(null);month.setBackground(SURFACE);month.setForeground(MUTED);
        switcher.setOpaque(false);switcher.add(week);switcher.add(month);
        bell=iconButton("bell","알림 · 추후 지원",40,()->{});bell.setDisabledIcon(bell.getIcon());bell.setEnabled(false);bell.setBorder(null);bell.setToolTipText("알림은 추후 지원할 예정이에요.");
        for(Component c:List.of(title,subtitle,range,previous,next,today,add,switcher,bell,error,daily,quick,mini,todos,goals))add(c);
        error.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));error.addMouseListener(new MouseAdapter(){public void mouseClicked(MouseEvent e){planner.reload();}});
        planner.status.addPropertyChangeListener("text",e->error.setText(planner.status.getText()));
        for(Card card:List.of(daily,mini,todos,goals))card.setLayout(null);
        put(daily,heading("오늘의 TODO",CARD_TITLE_SIZE),17,17,140,26);daily.add(day);
        previousDay=flat("‹","이전 날짜의 TODO",14,()->planner.navigateTasks(-1));nextDay=flat("›","다음 날짜의 TODO",14,()->planner.navigateTasks(1));daily.add(previousDay);daily.add(nextDay);daily.add(dailyScroll);
        addDaily=flat("＋   새로운 TODO 생성","오늘의 TODO 생성",10,()->editDaily(null));addDaily.setHorizontalAlignment(SwingConstants.LEFT);daily.add(addDaily);
        put(mini,monthTitle,17,17,150,26);miniPrevious=flat("‹","미니 달력 이전 달",14,()->moveMini(-1));miniNext=flat("›","미니 달력 다음 달",14,()->moveMini(1));mini.add(miniPrevious);mini.add(miniNext);dates.setOpaque(false);mini.add(dates);
        miniThisMonth=flat("이번 달","미니 달력 이번 달로 이동",10,()->{miniMonth=YearMonth.now(planner.clock);renderMini();});miniThisMonth.setForeground(NAVY);mini.add(miniThisMonth);
        addTodo=flat("＋","이번 주 TODO 생성",18,()->editTodo(null));put(todos,heading("이번 주 TODO",CARD_TITLE_SIZE),16,16,180,26);todos.add(addTodo);filters.setOpaque(false);todos.add(filterScroll);todos.add(todoScroll);
        addGoal=flat("＋","이번 주 목표 생성",18,()->editGoal(null));put(goals,heading("이번 주 목표",CARD_TITLE_SIZE),16,16,180,26);goals.add(addGoal);goals.add(goalScroll);
    }
    void refresh(){
        if(planner.calendar.getParent()!=this){add(planner.calendar);revalidate();}
        LocalDate start=weekStart(planner.anchor),end=start.plusDays(6);
        range.setText(start.format(DateTimeFormatter.ofPattern("uuuu년 M월 d일"))+" — "+(start.getMonth().equals(end.getMonth())?end.getDayOfMonth()+"일":end.format(DateTimeFormatter.ofPattern("M월 d일"))));
        if(shownAnchor==null||!shownAnchor.equals(planner.anchor)){miniMonth=YearMonth.from(planner.anchor);shownAnchor=planner.anchor;}
        renderMini();refreshDaily();renderTodos();renderGoals();writeEnabled(!planner.readFailed);
    }
    void writeEnabled(boolean enabled){for(JButton b:List.of(add,addDaily,addTodo,addGoal))b.setEnabled(enabled);}
    void editDaily(Task value){if(!planner.readFailed)showDialog(this,new PlannerWeekEditors.Daily(planner,value),"오늘의 TODO",480,470);}
    void editTodo(WeeklyTask value){if(!planner.readFailed)showDialog(this,new PlannerWeekEditors.Todo(planner,value),"이번 주 TODO",480,560);}
    void editGoal(WeeklyGoal value){if(!planner.readFailed)showDialog(this,new PlannerWeekEditors.GoalEditor(planner,value),"이번 주 목표",480,430);}
    void refreshDaily(){
        List<Task> values=planner.state.tasks().stream().filter(t->t.date().equals(planner.taskDate)).toList();
        DailyData data=new DailyData(planner.taskDate,values,planner.readFailed);if(data.equals(renderedDaily))return;renderedDaily=data;
        day.setText(planner.taskDate.format(DateTimeFormatter.ofPattern("M월 d일 (E)",java.util.Locale.KOREAN)));dailyRows.removeAll();
        for(Task task:values)dailyRows.add(new TodoRow(task.title(),task.detail(),task.completed(),true,()->planner.save(()->planner.store.toggleTask(task.id())),()->editDaily(task)));
        if(values.isEmpty())dailyRows.add(empty("오늘 하고 싶은 일을 적어보세요."));else{Component last=dailyRows.getComponent(dailyRows.getComponentCount()-1);last.setPreferredSize(new Dimension(1,20));last.setMaximumSize(new Dimension(Integer.MAX_VALUE,20));}dailyRows.revalidate();dailyRows.repaint();
    }
    List<WeeklyTask> weekTasks(){LocalDate start=weekStart(planner.anchor);return planner.state.weeklyTasks().stream().filter(t->t.week().equals(start)).toList();}
    void renderTodos(){
        List<WeeklyTask> values=weekTasks();
        TodoData data=new TodoData(weekStart(planner.anchor),values,planner.state.todoTags(),tagFilter,planner.readFailed);
        if(data.equals(renderedTodos))return;
        Map<String,Integer> counts=new HashMap<>();
        for(WeeklyTask task:values)for(String id:task.tagIds())counts.merge(id,1,Integer::sum);
        if(!tagFilter.isEmpty()&&(counts.getOrDefault(tagFilter,0)==0||planner.state.todoTags().stream().noneMatch(t->t.id().equals(tagFilter))))tagFilter="";
        renderedTodos=new TodoData(data.week(),values,data.tags(),tagFilter,data.readFailed());
        filters.removeAll();filters.add(filter("전체 "+values.size(),""));
        for(Tag tag:planner.state.todoTags()){
            int count=counts.getOrDefault(tag.id(),0);
            if(count>0)filters.add(filter(tag.name()+" "+count,tag.id()));
        }
        todoRows.removeAll();for(WeeklyTask task:values)if(tagFilter.isEmpty()||task.tagIds().contains(tagFilter)){
            TodoRow row=new TodoRow(task.title(),task.deadline()==null?"이번 주":task.deadline().format(DateTimeFormatter.ofPattern("M/d")),task.completed(),false,()->planner.save(()->planner.store.toggleWeeklyTask(task.id())),()->editTodo(task));
            row.setToolTipText(task.title()+" · "+(task.deadline()==null?"마감일 없음 - 이번 주 까지":"마감 "+task.deadline())+" · "+PlannerWeekEditors.weekLabel(task.week()));todoRows.add(row);
        }
        if(todoRows.getComponentCount()==0)todoRows.add(empty("이번 주 TODO를 추가해 보세요."));else trimLast(todoRows,21);filters.revalidate();todoRows.revalidate();todos.repaint();
    }
    JButton filter(String text,String id){JButton b=button(text,id.equals(tagFilter),()->{tagFilter=id;renderTodos();});b.setFont(medium(10));b.setBorder(null);b.setBackground(id.equals(tagFilter)?NAVY:SURFACE);b.setForeground(id.equals(tagFilter)?Color.WHITE:MUTED);b.setPreferredSize(new Dimension(Math.min(180,Math.max(56,b.getPreferredSize().width)),26));return b;}
    void renderGoals(){LocalDate week=weekStart(planner.anchor);List<WeeklyGoal> values=planner.state.weeklyGoals().stream().filter(g->g.week().equals(week)).toList();GoalData data=new GoalData(week,values,planner.readFailed);if(data.equals(renderedGoals))return;renderedGoals=data;goalRows.removeAll();for(WeeklyGoal goal:values)goalRows.add(new GoalRow(goal));if(goalRows.getComponentCount()==0)goalRows.add(empty("이번 주 목표를 정해 보세요."));else trimLast(goalRows,30);goalRows.revalidate();goalRows.repaint();}
    void moveMini(int amount){try{miniMonth=miniMonth.plusMonths(amount);renderMini();}catch(DateTimeException ignored){}}
    void renderMini(){
        if(miniMonth==null)return;MiniData data=new MiniData(miniMonth,planner.anchor);if(Objects.equals(renderedMini,data))return;renderedMini=data;monthTitle.setText(miniMonth.format(DateTimeFormatter.ofPattern("MMM uuuu",java.util.Locale.ENGLISH)).toUpperCase(java.util.Locale.ENGLISH));dates.removeAll();
        LocalDate first=weekStart(miniMonth.atDay(1));int weeks=(miniMonth.atDay(1).getDayOfWeek().getValue()-1+miniMonth.lengthOfMonth()+6)/7;
        dates.setLayout(new GridLayout(weeks+1,7,0,0));for(String d:new String[]{"M","T","W","T","F","S","S"}){JLabel l=label(d,9,MUTED);l.setHorizontalAlignment(SwingConstants.CENTER);dates.add(l);}
        for(int i=0;i<weeks*7;i++){LocalDate date=first.plusDays(i);boolean selected=date.equals(planner.anchor),inWeek=weekStart(date).equals(weekStart(planner.anchor)),current=YearMonth.from(date).equals(miniMonth);
            JButton b=new JButton(Integer.toString(date.getDayOfMonth())){
                @Override protected void paintComponent(Graphics graphics){
                    Graphics2D g=quality(graphics);
                    if(inWeek){
                        g.setColor(SURFACE);int radius=Math.min(8,Math.min(getWidth(),getHeight())/2);
                        if(date.getDayOfWeek()==DayOfWeek.MONDAY)g.fillRoundRect(0,0,getWidth()+radius,getHeight(),radius*2,radius*2);
                        else if(date.getDayOfWeek()==DayOfWeek.SUNDAY)g.fillRoundRect(-radius,0,getWidth()+radius,getHeight(),radius*2,radius*2);
                        else g.fillRect(0,0,getWidth(),getHeight());
                    }
                    if(selected){g.setColor(NAVY);g.fillRoundRect(1,1,getWidth()-2,getHeight()-2,getHeight(),getHeight());}
                    PlannerCalendar.center(g,getText(),selected?medium(10):regular(10),selected?Color.WHITE:current?INK:MUTED,0,0,getWidth(),getHeight());g.dispose();
                }
            };
            b.setUI(new BasicButtonUI());b.setOpaque(false);b.setContentAreaFilled(false);b.setBorder(null);b.setFocusPainted(false);b.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));name(b,"미니 달력 "+date);b.addActionListener(e->{planner.anchor=date;planner.taskDate=date;planner.refresh();});dates.add(b);
        }dates.revalidate();dates.repaint();
    }
    static int calendarWidth(int width){
        int pad=width<900?16:28,w=width-pad*2,gap=width<900?12:20;
        int side=w>=1000?288:Math.max(224,(int)(w*.23));return w<700?w:w-side-gap;
    }
    int minimumHeight(int width){int pad=width<900?16:28,w=width-pad*2;return pad+(w<940?132:84)+704+pad+(w<700?720:0);}
    static int headerBodyY(int width){int pad=width<900?16:28;return pad+(width-pad*2<940?132:84);}
    static String weekRange(LocalDate anchor){LocalDate start=weekStart(anchor),end=start.plusDays(6);return start.format(DateTimeFormatter.ofPattern("uuuu년 M월 d일"))+" — "+(start.getMonth().equals(end.getMonth())?end.getDayOfMonth()+"일":end.format(DateTimeFormatter.ofPattern("M월 d일")));}
    static int layoutHeader(int width,LocalDate anchor,JLabel title,JLabel subtitle,JLabel range,JLabel error,JButton previous,JButton today,JButton next,JButton add,JButton week,JButton month,JButton bell,JPanel switcher){
        int pad=width<900?16:28,gap=width<900?12:20,w=Math.max(1,width-pad*2),headerY=pad;
        boolean narrow=w<940;int actionY=headerY+(narrow?76:12),bodyY=headerY+(narrow?132:84);
        title.setFont(bold(width<600?22:26));int titleWidth=title.getPreferredSize().width;title.setBounds(pad,headerY-1,Math.max(244,titleWidth),40);subtitle.setBounds(pad+Math.max(width<600?218:241,titleWidth+8),headerY+10,90,20);
        range.setBounds(pad,headerY+42,Math.min(w,range.getFontMetrics(range.getFont()).stringWidth(weekRange(anchor))+4),22);
        int center=pad+calendarWidth(width)/2;
        int navY=(range.getY()+range.getHeight()+bodyY-NAV_BUTTON_SIZE)/2-8;
        int arrowInset=(NAV_BUTTON_SIZE-NAV_ARROW_SIZE)/2;
        if(center-NAV_GROUP_HALF<range.getX()+range.getWidth()+8){
            center=Math.min(width-pad-NAV_GROUP_HALF,range.getX()+range.getWidth()+8+NAV_GROUP_HALF);
            range.setSize(Math.max(1,Math.min(range.getWidth(),center-NAV_GROUP_HALF-range.getX()-8)),range.getHeight());
        }
        range.setToolTipText(range.getText());
        previous.setBounds(center-NAV_GROUP_HALF+arrowInset,navY+arrowInset,NAV_ARROW_SIZE,NAV_ARROW_SIZE);
        today.setBounds(center-NAV_TODAY_WIDTH/2,navY,NAV_TODAY_WIDTH,NAV_BUTTON_SIZE);
        next.setBounds(center+NAV_GROUP_HALF-NAV_BUTTON_SIZE+arrowInset,navY+arrowInset,NAV_ARROW_SIZE,NAV_ARROW_SIZE);
        int right=width-pad,bellSize=w<346?36:40,addWidth=w<346?124:140,switchWidth=w<346?132:142;
        bell.setBounds(right-bellSize,actionY,bellSize,40);add.setBounds(right-bellSize-12-addWidth,actionY,addWidth,40);
        switcher.setBounds(add.getX()-12-switchWidth,actionY+2,switchWidth,36);int tabWidth=(switchWidth-6)/2;week.setBounds(3,3,tabWidth,30);month.setBounds(3+tabWidth,3,switchWidth-6-tabWidth,30);
        // Tiny viewports retain the existing header height instead of adding a row.
        boolean crowded=List.of(previous,today,next).stream().anyMatch(nav->
            nav.getBounds().intersects(switcher.getBounds()) || nav.getBounds().intersects(add.getBounds()) || nav.getBounds().intersects(bell.getBounds()));
        if(crowded){
            int fallbackY=(title.getY()+title.getHeight()+range.getY()-NAV_BUTTON_SIZE)/2-8;
            for(JButton nav:List.of(previous,today,next))nav.setLocation(nav.getX(),fallbackY+(nav==today?0:arrowInset));
        }
        error.setBounds(pad,bodyY-20,w,18);return bodyY;
    }
    @Override public void doLayout(){
        int pad=getWidth()<900?16:28,gap=getWidth()<900?12:20,w=Math.max(1,getWidth()-pad*2);
        int bodyY=layoutHeader(getWidth(),planner.anchor,title,subtitle,range,error,previous,today,next,add,week,month,bell,switcher);
        int bodyH=Math.max(360,getHeight()-bodyY-pad-(w<700?720:0)),side=w>=1000?288:Math.max(224,(int)(w*.23)),left=w-side-gap;
        // Keep all cards readable at smaller widths; the outer scroll view supplies vertical room.
        if(w<700){left=w;side=w;}
        int bottom=192,calendarH=Math.max(200,bodyH-bottom-16);
        planner.calendar.setBounds(pad,bodyY,left,calendarH);
        int bottomY=bodyY+calendarH+16,dailyW=Math.round((left-16)*468/1050f);
        daily.setBounds(pad,bottomY,dailyW,bottom);quick.setBounds(pad+dailyW+16,bottomY,left-dailyW-16,bottom);
        int sideX=w<700?pad:pad+left+gap,sideY=w<700?bottomY+bottom+16:bodyY;
        int extra=Math.max(0,bodyH-704),todoH=264+extra/2,goalH=176+extra-extra/2;
        mini.setBounds(sideX,sideY,side,232);todos.setBounds(sideX,sideY+248,side,todoH);goals.setBounds(sideX,sideY+248+todoH+16,side,goalH);
        layoutDaily();monthTitle.setBounds(17,17,side-130,26);miniThisMonth.setBounds(side-108,18,54,24);miniPrevious.setBounds(side-50,18,16,24);miniNext.setBounds(side-30,18,16,24);dates.setBounds(17,50,side-34,mini.getHeight()-67);
        layoutList(todos,addTodo,todoScroll,true);layoutList(goals,addGoal,goalScroll,false);
    }
    void layoutDaily(){int w=daily.getWidth(),h=daily.getHeight();daily.getComponent(0).setBounds(17,17,110,26);day.setBounds(Math.max(128,w-180),20,128,20);previousDay.setBounds(w-48,18,16,22);nextDay.setBounds(w-28,18,16,22);dailyScroll.setBounds(17,51,Math.max(1,w-34),Math.max(1,h-88));addDaily.setBounds(17,h-31,Math.max(1,w-34),20);}
    void layoutList(Card card,JButton plus,JScrollPane list,boolean tagged){int w=card.getWidth();card.getComponent(0).setBounds(16,16,w-64,26);plus.setBounds(w-40,16,24,26);int top=50;if(tagged){int rows=filters.getLayout() instanceof WrapLayout layout?layout.height(filters,w-32):26;int filterHeight=Math.min(84,rows);filterScroll.setBounds(16,49,w-32,filterHeight);top=49+filterHeight+7;}list.setBounds(16,top,Math.max(1,w-32),Math.max(1,card.getHeight()-top-16));}
    @Override protected void paintComponent(Graphics graphics){super.paintComponent(graphics);Graphics2D g=quality(graphics);g.setColor(SURFACE);Rectangle r=switcher.getBounds();g.fillRoundRect(r.x,r.y,r.width,r.height,16,16);g.dispose();}
    static void trimLast(JPanel rows,int height){Component last=rows.getComponent(rows.getComponentCount()-1);last.setPreferredSize(new Dimension(1,height));last.setMaximumSize(new Dimension(Integer.MAX_VALUE,height));}
    static JPanel rows(){JPanel p=new JPanel();p.setLayout(new BoxLayout(p,BoxLayout.Y_AXIS));p.setBackground(Color.WHITE);return p;}
    static JLabel empty(String text){JLabel label=label(text,11,MUTED);label.setPreferredSize(new Dimension(1,28));label.setMaximumSize(new Dimension(Integer.MAX_VALUE,28));return label;}
    static JScrollPane quietScroll(Component view){JScrollPane s=scroll(view);s.setOpaque(false);s.getVerticalScrollBar().setUI(new FadingScrollBarUI(Color.BLACK,.18f));s.getVerticalScrollBar().setPreferredSize(new Dimension(8,1));return s;}
    static JButton flat(String text,String name,int size,Runnable action){JButton b=button(text,false,action);b.setBorder(null);b.setBackground(Color.WHITE);b.setFont(regular(size));b.setForeground(MUTED);PlannerStyle.name(b,name);return b;}
    static JButton navigationButton(String text,String name,boolean circle,Runnable action){
        JButton button=new JButton(text){@Override protected void paintComponent(Graphics graphics){
            Graphics2D g=quality(graphics);int width=getWidth()-2,height=getHeight()-2,arc=circle?height:14;
            double cx=getWidth()/2.0,cy=getHeight()/2.0;
            g.setColor(new Color(0,40,96,10));g.fillRoundRect(1,2,width,height,arc,arc);
            g.setColor(getModel().isPressed()?new Color(0xeaf0f7):getModel().isRollover()?new Color(0xf8faff):new Color(255,255,255,235));
            g.fillRoundRect(1,1,width,height,arc,arc);
            g.setColor(hasFocus()?new Color(0,40,96,110):new Color(0,40,96,24));
            g.draw(new java.awt.geom.RoundRectangle2D.Double(1.5,1.5,width-1,height-1,arc,arc));
            g.setColor(getForeground());
            if(circle){
                double direction=text.equals("‹")?-1:1;
                var chevron=new java.awt.geom.Path2D.Double();
                chevron.moveTo(cx-direction*2.4,cy-4.32);chevron.lineTo(cx+direction*2.4,cy);chevron.lineTo(cx-direction*2.4,cy+4.32);
                g.setStroke(new BasicStroke(1.536f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));g.draw(chevron);
            }else{
                var layout=new java.awt.font.TextLayout(getText(),getFont(),g.getFontRenderContext());
                var ink=layout.getBounds();layout.draw(g,(float)(cx-ink.getCenterX()),(float)(cy-ink.getCenterY()));
            }
            g.dispose();
        }};
        button.setUI(new BasicButtonUI());button.setBorder(BorderFactory.createEmptyBorder());button.setContentAreaFilled(false);button.setOpaque(false);button.setFocusPainted(false);
        button.setFont(medium(12));button.setForeground(NAVY);button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        name(button,name);button.setToolTipText(name);button.addActionListener(event->action.run());return button;
    }
    static JCheckBox todoCheck(){JCheckBox c=taskCheck();Icon unchecked=new Icon(){public int getIconWidth(){return 14;}public int getIconHeight(){return 14;}public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=quality(graphics);g.setColor(Color.WHITE);g.fillRoundRect(x,y,13,13,5,5);g.setColor(BORDER);g.drawRoundRect(x,y,13,13,5,5);g.dispose();}};c.setIcon(unchecked);c.setSelectedIcon(new Icon(){public int getIconWidth(){return 14;}public int getIconHeight(){return 14;}public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=quality(graphics);g.setColor(NAVY);g.fillRoundRect(x,y,14,14,6,6);icon("task-check",10).paintIcon(c,g,x+2,y+2);g.dispose();}});return c;}
    abstract static class HoverRow extends JPanel {
        boolean hover;
        HoverRow(int height){super(null);setOpaque(false);setPreferredSize(new Dimension(1,height));setMaximumSize(new Dimension(Integer.MAX_VALUE,height));}
        void installHover(){MouseAdapter listener=new MouseAdapter(){@Override public void mouseEntered(MouseEvent e){active(true);}@Override public void mouseExited(MouseEvent e){Point at=SwingUtilities.convertPoint(e.getComponent(),e.getPoint(),HoverRow.this);if(!contains(at))active(false);}};hook(this,listener);}
        void hook(Component c,MouseAdapter listener){c.addMouseListener(listener);if(c instanceof AbstractButton)c.addFocusListener(new FocusAdapter(){@Override public void focusGained(FocusEvent e){active(true);}@Override public void focusLost(FocusEvent e){SwingUtilities.invokeLater(()->{Component owner=KeyboardFocusManager.getCurrentKeyboardFocusManager().getFocusOwner();if(owner==null||!SwingUtilities.isDescendingFrom(owner,HoverRow.this))active(false);});}});if(c instanceof Container box)for(Component child:box.getComponents())hook(child,listener);}
        void active(boolean value){if(hover==value)return;hover=value;ScrollCacheViewport.invalidateContent(this);doLayout();repaint();}
    }
    final class TodoRow extends HoverRow {
        final String text,detail;final boolean completed,daily;final JCheckBox check=todoCheck();final JButton title,edit;
        TodoRow(String text,String detail,boolean completed,boolean daily,Runnable toggle,Runnable change){
            super(28);this.text=text;this.detail=detail;this.completed=completed;this.daily=daily;
            check.setSelected(completed);check.setEnabled(!planner.readFailed);name(check,text+" 완료");check.addActionListener(e->toggle.run());add(check);
            title=flat("",text,daily?11:10,change);title.setHorizontalAlignment(SwingConstants.LEFT);title.setToolTipText(text+(detail.isBlank()?"":" · "+detail));add(title);
            edit=editButton(text+" 편집",change);add(edit);setComponentZOrder(edit,0);installHover();
        }
        @Override public void doLayout(){check.setBounds(0,daily?3:6,14,16);title.setBounds(daily?26:22,0,Math.max(1,getWidth()-(daily?26:22)),24);edit.setBounds(Math.max(0,getWidth()-20),2,20,20);edit.setVisible(hover);edit.setEnabled(!planner.readFailed);}
        @Override protected void paintChildren(Graphics graphics){
            super.paintChildren(graphics);Graphics2D g=quality(graphics);int x=daily?26:22,max=Math.max(0,getWidth()-x-(hover?24:0));g.clipRect(x,0,max,24);
            Font font=daily?medium(11):regular(10);g.setFont(font);int width=Math.min(max,g.getFontMetrics().stringWidth(text));g.setColor(completed?MUTED:INK);g.drawString(text,x,16);
            if(completed)g.drawLine(x,12,x+width,12);if(hover)g.drawLine(x,19,x+width,19);
            if(daily&&!detail.isBlank()){int dx=x+g.getFontMetrics().stringWidth(text)+12;g.setFont(regular(10));g.setColor(MUTED);g.drawString(detail,dx,16);}else if(!daily){g.setColor(Color.WHITE);g.fillRect(Math.max(x,getWidth()-(hover?68:44)),0,44,24);g.setFont(regular(9));g.setColor(MUTED);g.drawString(detail,getWidth()-(hover?68:44),16);}
            g.dispose();
        }
    }
    final class GoalRow extends HoverRow {
        final WeeklyGoal goal;final JButton title,edit,minus,plus;
        GoalRow(WeeklyGoal goal){super(39);this.goal=goal;
            title=flat("",goal.title(),10,()->editGoal(goal));title.setToolTipText(goal.title());add(title);edit=editButton(goal.title()+" 목표 편집",()->editGoal(goal));add(edit);
            minus=step("−",goal.title()+" 성공 횟수 감소",()->planner.save(()->planner.store.adjustWeeklyGoal(goal.id(),-1)));plus=step("+",goal.title()+" 성공 횟수 증가",()->planner.save(()->planner.store.adjustWeeklyGoal(goal.id(),1)));add(minus);add(plus);setComponentZOrder(edit,0);setComponentZOrder(minus,0);setComponentZOrder(plus,0);installHover();
        }
        @Override public void doLayout(){int w=getWidth();title.setBounds(0,0,Math.max(1,w-42),22);edit.setBounds(w-110,0,20,20);minus.setBounds(w-87,0,20,20);plus.setBounds(w-64,0,20,20);for(JButton b:List.of(edit,minus,plus))b.setVisible(hover);edit.setEnabled(!planner.readFailed);minus.setEnabled(!planner.readFailed&&goal.completed()>0);plus.setEnabled(!planner.readFailed&&goal.completed()<goal.target());}
        @Override protected void paintChildren(Graphics graphics){super.paintChildren(graphics);Graphics2D g=quality(graphics);int w=getWidth();Graphics2D text=(Graphics2D)g.create();text.clipRect(0,0,Math.max(1,w-(hover?114:44)),23);text.setFont(regular(10));text.setColor(INK);text.drawString(goal.title(),0,14);if(hover)text.drawLine(0,17,text.getFontMetrics().stringWidth(goal.title()),17);text.dispose();g.setFont(regular(9));g.setColor(MUTED);String progress=goal.completed()+" / "+goal.target();g.drawString(progress,w-g.getFontMetrics().stringWidth(progress),14);g.setColor(SURFACE);g.fillRoundRect(0,24,w,6,6,6);g.setColor(NAVY);g.fillRoundRect(0,24,(int)Math.round(w*goal.completed()/(double)goal.target()),6,6,6);g.dispose();}
    }
    static JButton step(String text,String name,Runnable action){JButton b=button(text,false,action);b.putClientProperty("planner.compact",true);b.setFont(regular(12));PlannerStyle.name(b,name);return b;}
    static JButton editButton(String name,Runnable action){JButton b=flat("",name,12,action);b.setIcon(RecordingPanelIcon.edit());return b;}
    /** Reuse the existing edit asset rather than introducing another icon style. */
    private static final class RecordingPanelIcon {
        static final Icon EDIT=new ImageIcon(PlannerWeekView.class.getResource("/dev/synesis/poc/recording/edit.png")){
            @Override public int getIconWidth(){return 14;}@Override public int getIconHeight(){return 14;}
            @Override public void paintIcon(Component c,Graphics g,int x,int y){g.drawImage(getImage(),x,y,14,14,null);}
        };
        static Icon edit(){return EDIT;}
    }
    static final class WrapLayout extends FlowLayout {
        WrapLayout(){super(FlowLayout.LEFT,5,4);}
        int height(Container target,int width){int lines=1,x=0;for(Component child:target.getComponents()){int w=child.getPreferredSize().width;if(x>0&&x+w>width){lines++;x=0;}x+=w+5;}return lines*30;}
        @Override public Dimension preferredLayoutSize(Container target){int w=target.getParent() instanceof JViewport v?v.getWidth():target.getWidth();return new Dimension(Math.max(1,w),height(target,Math.max(1,w)));}
    }
    static final class QuickNote extends Card {
        QuickNote(){super(Color.WHITE,12);setToolTipText("Quick Note 디자인 미리보기 · 편집 기능은 추후 구현해요.");name(this,"Quick Note 디자인 미리보기");}
        @Override protected void paintComponent(Graphics graphics){super.paintComponent(graphics);Graphics2D g=quality(graphics);int split=Math.max(100,Math.round(getWidth()*176/582f)),right=split+1;g.setColor(new Color(0xf6f8fc));g.fillRoundRect(1,1,split,getHeight()-2,22,22);g.fillRect(12,1,split-12,getHeight()-2);g.setColor(BORDER);g.drawLine(split+1,1,split+1,getHeight()-1);
            drawText(g,"Quick Note",bold(CARD_TITLE_SIZE),INK,11,11,split-40);drawText(g,"4",regular(10),MUTED,112,15,20);drawText(g,"＋",regular(17),NAVY,split-27,8,20);
            String[] names={"Synesis PDF 모듈","전시 감상 에세이","금융의 이해 요약","UI 리디자인 아이디어"};for(int i=0;i<names.length;i++){int y=41+i*34;if(i==0){g.setColor(new Color(0xe5edf9));g.fillRoundRect(11,y,split-20,28,10,10);}drawText(g,"≡",regular(12),i==0?NAVY:MUTED,17,y+4,12);drawText(g,names[i],i==0?medium(10):regular(10),i==0?NAVY:new Color(0x595959),36,y+6,split-42);}
            int x=right+14,w=Math.max(1,getWidth()-x-14);drawText(g,"Synesis PDF 모듈",bold(14),INK,x,17,w-50);drawText(g,"↗   ···",regular(14),MUTED,getWidth()-66,17,54);drawText(g,"본문",regular(10),MUTED,x,48,22);drawText(g,"⌄",new Font(Font.DIALOG,Font.PLAIN,11),MUTED,x+24,48,12);drawText(g,"B",bold(11),MUTED,x+42,48,12);drawText(g,"I",medium(11),MUTED,x+64,48,12);drawText(g,"≡",regular(13),MUTED,x+82,46,16);drawText(g,"☑",new Font(Font.DIALOG,Font.PLAIN,11),MUTED,x+109,48,16);
            drawText(g,"이번 주 구현할 기능",medium(10),INK,x,72,w);String[] lines={"• PDF 업로드와 미리보기 흐름 정리","• 문서별 학습 메모 연결","• 오류 재현과 저장 상태 점검"};for(int i=0;i<lines.length;i++)drawText(g,lines[i],regular(10),new Color(0x595959),x,91+i*16,w);
            drawText(g,"자동 저장됨",regular(9),new Color(0x949494),x,getHeight()-35,w-80);drawText(g,"10월 14일 수정",regular(9),new Color(0x949494),getWidth()-86,getHeight()-35,74);g.dispose();}
    }
    static JButton eventButton(Occurrence o,boolean compact,State state,Runnable edit){return PlannerWeekCalendarSkin.eventButton(o,compact,state,edit);}
}
