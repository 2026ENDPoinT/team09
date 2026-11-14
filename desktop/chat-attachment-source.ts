import { isCourseId, type AssignmentDetails } from "../shared/assignment-browser.js";

type Fields = Record<string, unknown>;

function object(value: unknown): value is Fields {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function attachmentIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((file) => object(file) && typeof file.id === "string" ? [file.id] : []);
}

function assignmentFileKey(course: string, post: unknown, attachment: string): string {
  return JSON.stringify([course, post, attachment]);
}

function matchesLocator(args: Fields, locator: Fields): boolean {
  return Object.entries(locator).every(([key, value]) => args[key] === undefined || args[key] === value);
}

export function createAttachmentSources(previousReads: { name: string; args: Fields }[], assignment?: AssignmentDetails) {
  const collectionCourses = new Map<string, Set<string>>();
  const assignmentAttachments = new Set<string>();

  if (assignment) for (const { id } of assignment.attachments ?? []) {
    assignmentAttachments.add(assignmentFileKey(assignment.courseId, assignment.assignmentId, id));
  }

  function rememberCollectionFile(course: string, id: string) {
    const courses = collectionCourses.get(id) ?? new Set<string>();
    courses.add(course);
    collectionCourses.set(id, courses);
  }

  function remember(name: unknown, args: Fields, result: unknown) {
    const course = args.course_id;
    if (!isCourseId(course) || (object(result) && result.status != null && result.status !== "ok")) return;
    if (name === "list_course_files") {
      const files = object(result) ? result.result : result;
      for (const id of attachmentIds(files)) rememberCollectionFile(course, id);
    } else if (name === "get_post" && args.kind === "assignment" && object(result) && typeof args.post_id === "string") {
      for (const id of attachmentIds(result.attachments)) {
        assignmentAttachments.add(assignmentFileKey(course, args.post_id, id));
      }
    }
  }

  for (const { name, args } of previousReads) {
    const { course_id: course, attachment_id: id, post_id: post } = args;
    if (name !== "read_attachment" || !isCourseId(course) || typeof id !== "string") continue;
    if (args.kind === "file_collection") rememberCollectionFile(course, id);
    if (args.kind === "assignment" && typeof post === "string") assignmentAttachments.add(assignmentFileKey(course, post, id));
  }

  function readArgs(args: Fields): Fields {
    if (args.kind !== "assignment" && args.kind !== "file_collection") return args;
    if (typeof args.attachment_id !== "string") return args;
    const courses = collectionCourses.get(args.attachment_id);
    if (!courses) return args;
    const course = args.course_id ?? (courses.size === 1 ? courses.values().next().value : undefined);
    if (!isCourseId(course) || !courses.has(course)) return args;
    // A file may appear in the collection and as a verified post attachment.
    if (args.kind === "assignment" && assignmentAttachments.has(assignmentFileKey(course, args.post_id, args.attachment_id))) return args;
    const { post_id: _post, board_id: _board, page: _page, ...read } = args;
    return { ...read, kind: "file_collection", course_id: course };
  }

  function currentPostArgs(args: Fields): Fields | undefined {
    if (!assignment) return;
    const locator = { kind: "assignment", course_id: assignment.courseId, post_id: assignment.assignmentId };
    if (matchesLocator(args, locator)) return locator;
  }

  function currentReadArgs(args: Fields): Fields | undefined {
    const id = args.attachment_id;
    if (typeof id !== "string") return;
    const post = currentPostArgs(args);
    if (post && assignment && assignmentAttachments.has(assignmentFileKey(assignment.courseId, assignment.assignmentId, id))) {
      const { board_id: _board, page: _page, ...read } = args;
      return { ...read, ...post };
    }
    const matches = previousReads.filter((ref) => ref.name === "read_attachment" && ref.args.attachment_id === id &&
      typeof ref.args.kind === "string" && isCourseId(ref.args.course_id) &&
      ["kind", "course_id", "post_id", "board_id", "page"].every((key) => args[key] === undefined || args[key] === ref.args[key]));
    if (matches.length === 1) return { ...args, ...matches[0].args };
  }

  return { remember, readArgs, currentPostArgs, currentReadArgs };
}
