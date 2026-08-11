import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ExternalLink, GripVertical, Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type CourseOut } from "../../lib/api";
import { Announcements } from "./Announcements";
import { CourseDialog } from "./CourseDialog";
import { HomeWidgets } from "./HomeWidgets";
import "./home.css";

function CourseCard({
  course,
  onEdit,
}: {
  course: CourseOut;
  onEdit: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: course.id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 2 : undefined,
    opacity: isDragging ? 0.85 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`course-card-wrap${isDragging ? " dragging" : ""}`}
    >
      <Link
        to="/courses/$courseId"
        params={{ courseId: String(course.id) }}
        className="course-card"
      >
        {course.cover_image_url ? (
          <div className="course-cover">
            <img src={course.cover_image_url} alt="" />
          </div>
        ) : (
          <span
            className="course-accent"
            style={{ background: course.accent_color ?? "var(--accent-blue)" }}
          />
        )}
        <div className="course-card-body">
          <span className="course-code">{course.code}</span>
          <span className="course-name">{course.name}</span>
          <span className="course-meta">
            {course.module_count}{" "}
            {course.module_count === 1 ? "module" : "modules"}
            {course.document_count > 0 && ` · ${course.document_count} docs`}
            {course.card_count > 0 && ` · ${course.card_count} cards`}
            {course.term ? ` · ${course.term}` : ""}
          </span>
        </div>
      </Link>
      <div className="course-card-actions">
        <button
          className="icon-btn course-drag"
          aria-label={`Reorder ${course.code}`}
          title="Drag to reorder"
          {...attributes}
          {...listeners}
        >
          <GripVertical size={13} strokeWidth={1.5} />
        </button>
        <button
          className="icon-btn"
          onClick={onEdit}
          aria-label={`Edit ${course.code}`}
          title="Edit course (cover, meeting link, color, delete…)"
        >
          <Pencil size={13} strokeWidth={1.5} />
        </button>
        {course.canvas_url && (
          <a
            className="icon-btn"
            href={course.canvas_url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open ${course.code} in Canvas`}
            title="Open in Canvas"
          >
            <ExternalLink size={13} strokeWidth={1.5} />
          </a>
        )}
      </div>
    </div>
  );
}

export function HomePage() {
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<null | { course: CourseOut | null }>(null);
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
  });

  // Local order for a smooth optimistic drag; re-synced whenever the server list changes.
  const [order, setOrder] = useState<CourseOut[]>([]);
  useEffect(() => {
    if (courses.data) setOrder(courses.data);
  }, [courses.data]);

  const reorder = useMutation({
    mutationFn: (ids: number[]) => api.put("/api/courses/reorder", { ids }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
  });

  const sensors = useSensors(
    // small distance so a click still navigates; a deliberate drag reorders
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const oldIndex = order.findIndex((c) => c.id === active.id);
    const newIndex = order.findIndex((c) => c.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(order, oldIndex, newIndex);
    setOrder(next);
    reorder.mutate(next.map((c) => c.id));
  }

  return (
    <div className="home">
      <header className="home-head">
        <h1>Your Courses</h1>
        <button
          className="btn btn-primary"
          onClick={() => setDialog({ course: null })}
        >
          <Plus size={16} strokeWidth={2} /> New course
        </button>
      </header>

      <HomeWidgets />
      <Announcements />

      {courses.isLoading && <div className="home-empty">Loading…</div>}
      {courses.isError && (
        <div className="home-empty">
          <p>Could not load courses — is the server running?</p>
        </div>
      )}
      {courses.data && courses.data.length === 0 && (
        <div className="home-empty">
          <p>
            No courses yet. Create your first course to start organizing your
            study materials.
          </p>
        </div>
      )}

      {order.length > 0 && (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
        >
          <SortableContext
            items={order.map((c) => c.id)}
            strategy={rectSortingStrategy}
          >
            <div className="course-grid">
              {order.map((course) => (
                <CourseCard
                  key={course.id}
                  course={course}
                  onEdit={() => setDialog({ course })}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      {dialog && (
        <CourseDialog course={dialog.course} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}
