import { CONFIRMATION_STATUSES, COURSE_WEEKDAYS, RIDE_REQUEST_STATUSES } from './contracts.js';

/**
 * Validate that a value is a non-empty string.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Validate a day-of-week value.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidWeekday(value) {
  return typeof value === 'string' && COURSE_WEEKDAYS.includes(value);
}

/**
 * Validate a confirmation status.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidConfirmationStatus(value) {
  return typeof value === 'string' && CONFIRMATION_STATUSES.includes(value);
}

/**
 * Validate a ride request status.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidRideRequestStatus(value) {
  return typeof value === 'string' && RIDE_REQUEST_STATUSES.includes(value);
}

/**
 * Validate a time string using HH:mm format.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidTimeString(value) {
  if (typeof value !== 'string') {
    return false;
  }

  return /^([01]\d|2[0-3]):([0-5]\d)$/.test(value);
}

/**
 * Validate a basic course object.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidCourse(value) {
  if (!value || typeof value !== 'object') {
    return false;
  }

  return (
    isNonEmptyString(value.courseCode) &&
    isNonEmptyString(value.courseName) &&
    isNonEmptyString(value.section) &&
    Array.isArray(value.meetingPatterns) &&
    value.meetingPatterns.every((pattern) => (
      isValidWeekday(pattern?.dayOfWeek) &&
      isValidTimeString(pattern?.startTime) &&
      isValidTimeString(pattern?.endTime)
    )) &&
    isNonEmptyString(value.location)
  );
}
